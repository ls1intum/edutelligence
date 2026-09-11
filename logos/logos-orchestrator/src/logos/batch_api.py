"""OpenAI Batch API support.

Logos serves the Batch API surface — ``/v1/files`` for the input/output files
and ``/v1/batches`` for the job lifecycle, plus the ``openai/`` and ``jobs/``
mirrors — by forwarding each operation to the Batch API of a cloud provider the
calling key may use. The job itself runs at the provider, on its batch
endpoint, which is the whole point: that is where the provider's batch rate
applies, and a fan-out Logos ran itself would pay the standard rate.

What Logos keeps is everything a proxy exists for:

* **Authorisation.** A batch body carries no ``model``, so the provider is
  resolved from the key's provider permissions. That alone would say nothing
  about *what* the batch runs, so every request line of the input file is
  checked against the key's model permissions before the file is accepted.
* **Ownership.** File and batch ids live at the provider and are used for hours
  after the call that minted them, with a credential shared by every key that
  may use the provider. Each id is therefore recorded with its owning team
  (``batch_objects``), and a lifecycle call for an id another team owns is
  answered exactly like one that never existed.
* **Billing.** When a batch reaches a terminal state its output file is read
  once and each result row is booked as an ordinary usage row with
  ``service_tier='batch'``, so batch spend lands in the same budget,
  statistics and export surfaces as everything else — priced at the provider's
  batch rate where one is configured.

Addressing differs per upstream: Azure serves Batch at the resource level
(``{host}/openai/v1/batches``, no deployment segment) while an OpenAI-shaped
provider is addressed under its own ``base_url``. Azure also names models by
*deployment*, so the input file's model names are translated on the way in and
back on the way out.
"""

import asyncio
import json
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

from logos.auth import AuthContext, authenticate_batch_api_key
from logos.batch_local import local_batch_object, local_file_object, new_object_id, parse_request_lines, run_local_batch
from logos.benchmarks.guidellm_runner import credential_transport_is_secure
from logos.billing.budget import check_monthly_budget
from logos.billing.finalize import finalize_billing_inputs
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.types import cloud_auth_header
from logos.errors import openai_error_response, raise_openai_error
from logos.request_content import parse_batch_file_upload, sanitized_headers_for_persistence, strip_proxy_prefixes
from logos.responses import get_client_ip
from logos.sdi.azure_deployment_sync import azure_host_from_base_url
from logos.sdi.providers.azure_provider import extract_azure_deployment_name

logger = logging.getLogger(__name__)

# Header a client with more than one Batch-capable provider uses to name the
# one it wants. Compared case-insensitively: Starlette lowercases header names.
BATCH_PROVIDER_HEADER = "X-Logos-Provider"

# Forces where a batch runs: 'provider' (fail if no provider Batch API applies),
# 'logos' (run it here even when a provider could), or 'auto' (the default —
# forward when possible, because that is where the batch rate is).
BATCH_EXECUTION_HEADER = "X-Logos-Batch-Execution"

# Azure serves Batch at the resource level. The ``/openai/v1`` surface is the
# addressing that carries newer models and needs no api-version; the dated
# data-plane route stays reachable through the env override for a resource that
# only serves that one. (Verified against the production resource: the batch
# routes answer under /openai/v1 and under 2024-10-21 or later, while the
# 2024-02-01 data-plane version 404s.)
AZURE_BATCH_API_VERSION = os.getenv("LOGOS_AZURE_BATCH_API_VERSION", "").strip()

# Batch operations are control-plane calls plus the file transfer around them,
# not inference, so a real timeout applies here.
_BATCH_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=10.0)

# A batch result file is read in one go; give it room but keep it bounded.
_SETTLE_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=60.0, pool=10.0)

# How long a provider's probed Batch API capability is trusted before it is
# re-probed. A provider gains or loses the surface rarely, so this is generous.
CAPABILITY_TTL = timedelta(hours=int(os.getenv("LOGOS_BATCH_CAPABILITY_TTL_HOURS", "24")))

# Request lines per batch input file. OpenAI and Azure both cap a batch at
# 50 000 requests; rejecting here names the file rather than the upstream.
MAX_BATCH_REQUESTS = int(os.getenv("LOGOS_MAX_BATCH_REQUESTS", "50000"))

# How often the reconciler looks for batches that finished while nobody polled.
RECONCILE_INTERVAL_S = int(os.getenv("LOGOS_BATCH_RECONCILE_INTERVAL_S", "300"))

# How long a settlement's exclusive claim on a batch lasts. Settlement is a
# download plus a ledger write, so this is generous; it only matters in the
# failure case, where a shorter lease means the retried settlement can start
# sooner after the first one died.
SETTLEMENT_LEASE_TTL_S = int(os.getenv("LOGOS_BATCH_SETTLEMENT_LEASE_TTL_S", "1800"))

# The operations a batch request line may address. A batch is an inference
# channel; the Files API is its transport, not a general object store.
_BATCH_REQUEST_ENDPOINTS = {
    "chat/completions",
    "responses",
    "embeddings",
}

# Batch states the provider will not move away from on its own.
TERMINAL_BATCH_STATES = {"completed", "failed", "expired", "cancelled"}

_MIRROR_PREFIXES = ("jobs/", "openai/")


def _http_client() -> httpx.AsyncClient:
    """Outbound client factory — a seam tests replace with a MockTransport."""
    return httpx.AsyncClient(follow_redirects=False)


@dataclass(frozen=True)
class BatchOperation:
    """One inbound Batch API call, normalised across the proxy prefixes.

    ``path`` is the canonical ``v1/...`` form: the ``jobs/`` and ``openai/``
    mirrors are peeled and the version segment restored, because a generic
    provider is addressed like-for-like on that path and its ``base_url`` may
    not carry the version itself.
    """

    resource: str  # "files" | "batches"
    method: str
    path: str  # e.g. "v1/files/file-123"
    query: str = ""
    resource_id: Optional[str] = None
    suboperation: Optional[str] = None  # "content" (files) | "cancel" (batches)

    @property
    def is_file_upload(self) -> bool:
        return self.resource == "files" and self.method == "POST" and self.resource_id is None

    @property
    def is_batch_creation(self) -> bool:
        return self.resource == "batches" and self.method == "POST" and self.resource_id is None

    @property
    def is_listing(self) -> bool:
        return self.method == "GET" and self.resource_id is None


def _canonical_path(path: str, resource: str, resource_id: Optional[str], suboperation: Optional[str]) -> str:
    """The ``v1/...`` spelling of an operation, whichever mirror it arrived on."""
    tail = resource
    if resource_id:
        tail = f"{tail}/{resource_id}"
    if suboperation:
        tail = f"{tail}/{suboperation}"
    return f"v1/{tail}"


def parse_batch_api_path(path: str, method: str = "POST", query: str = "") -> Optional[BatchOperation]:
    """Parse an inbound Batch API path into its operation.

    ``is_batch_api_path`` (request_content) is the cheap membership test; this
    recovers the resource id and suboperation the forwarder needs and returns
    ``None`` for shapes that are not one of the Batch API routes (e.g.
    ``batches/<id>/unknown``) so the caller can 404 them cleanly.
    """
    normalized = strip_proxy_prefixes(path)
    segments = [segment for segment in normalized.split("/") if segment]
    if not segments or segments[0] not in {"batches", "files"}:
        return None
    resource = segments[0]
    if len(segments) == 1:
        return BatchOperation(
            resource=resource, method=method, path=_canonical_path(path, resource, None, None), query=query
        )
    if len(segments) == 2:
        return BatchOperation(
            resource=resource,
            method=method,
            path=_canonical_path(path, resource, segments[1], None),
            query=query,
            resource_id=segments[1],
        )
    if len(segments) == 3:
        suboperation = {"files": "content", "batches": "cancel"}.get(resource)
        if segments[2] == suboperation:
            return BatchOperation(
                resource=resource,
                method=method,
                path=_canonical_path(path, resource, segments[1], segments[2]),
                query=query,
                resource_id=segments[1],
                suboperation=segments[2],
            )
    return None


def _generic_tail(base_url: str, path: str) -> str:
    """The operation path a generic cloud provider is addressed under.

    Mirrors ``ContextResolver._cloud_forward_url``: the canonical path, with the
    version prefix deduplicated when the provider's base_url already ends in it
    (``.../v1`` + ``v1/batches`` → ``.../v1/batches``).
    """
    base = base_url.rstrip("/")
    tail = path.lstrip("/")
    for prefix in ("v1/", "v2/"):
        if base.endswith("/" + prefix.rstrip("/")) and tail.startswith(prefix):
            tail = tail[len(prefix) :]
            break
    return tail


def _batch_tail(operation: BatchOperation) -> str:
    tail = operation.resource
    if operation.resource_id:
        tail = f"{tail}/{operation.resource_id}"
    if operation.suboperation:
        tail = f"{tail}/{operation.suboperation}"
    return tail


def is_azure_provider(provider: Dict[str, Any]) -> bool:
    return str(provider.get("cloud_provider_type") or "").lower() == "azure"


def batch_base_url(provider: Dict[str, Any]) -> str:
    """Where this provider's Batch API root lives, without the operation."""
    base_url = (provider.get("base_url") or "").strip()
    if not base_url:
        raise_openai_error(
            502,
            f"Provider {provider.get('name')} has no base_url configured and cannot serve the Batch API",
            code="batch_upstream_unreachable",
        )
    if not is_azure_provider(provider):
        return base_url.rstrip("/")
    host = azure_host_from_base_url(base_url).rstrip("/")
    return f"{host}/openai" if AZURE_BATCH_API_VERSION else f"{host}/openai/v1"


def batch_operation_url(provider: Dict[str, Any], operation: BatchOperation) -> str:
    """Build the upstream URL for one Batch API operation.

    Azure's Batch API lives at the resource level (no deployment segment), so it
    is addressed on the resource host derived from the provider base_url. Every
    other OpenAI-shaped provider is addressed by appending the canonical
    operation path to its base_url, exactly like the inference forward.
    """
    base = batch_base_url(provider)
    if is_azure_provider(provider):
        query = operation.query
        if AZURE_BATCH_API_VERSION and "api-version=" not in query:
            query = (
                f"{query}&api-version={AZURE_BATCH_API_VERSION}" if query else f"api-version={AZURE_BATCH_API_VERSION}"
            )
        return f"{base}/{_batch_tail(operation)}" + (f"?{query}" if query else "")
    return f"{base}/{_generic_tail(base, operation.path)}" + (f"?{operation.query}" if operation.query else "")


def batch_provider_headers(provider: Dict[str, Any]) -> Dict[str, str]:
    """The auth header the provider's stored credentials produce for batch calls.

    Azure batch routes authenticate with the resource ``api-key`` header the
    deployment sync already uses; everything else follows the provider's stored
    ``auth_name`` / ``auth_format`` (empty is legitimate for an upstream that
    serves unauthenticated).
    """
    api_key = provider.get("api_key")
    if is_azure_provider(provider):
        if not api_key:
            raise_openai_error(
                502,
                f"Azure provider {provider.get('name')} has no API key configured for its Batch API",
                code="batch_upstream_unreachable",
            )
        return {"api-key": api_key}
    header = cloud_auth_header(
        provider.get("auth_name"),
        provider.get("auth_format"),
        api_key,
        str(provider.get("cloud_provider_type") or "") or None,
    )
    return {} if header is None else {header[0]: header[1]}


def _assert_secure_transport(provider: Dict[str, Any], url: str, headers: Dict[str, str]) -> None:
    if headers and not credential_transport_is_secure(url):
        logger.error(
            "Refusing to send the credentials of provider %s (%s) over an insecure transport (%s)",
            provider.get("id"),
            provider.get("name"),
            url.split("?", 1)[0],
        )
        raise_openai_error(
            502,
            "The Batch API provider is configured over an insecure transport; Logos will not "
            "send its credentials there.",
            code="batch_upstream_unreachable",
        )


# ---------------------------------------------------------------------------
# Choosing where a batch runs
# ---------------------------------------------------------------------------


async def probe_batch_capability(provider: Dict[str, Any]) -> Tuple[bool, str]:
    """Ask a provider whether it serves the Batch API at all.

    Being a cloud provider says nothing about this: an OpenAI-shaped resource
    can be a self-hosted inference endpoint that serves chat and nothing else.
    A listing call is the cheapest question that distinguishes them, and its
    answer is cached so this runs about once a day per provider.
    """
    listing = BatchOperation(resource="batches", method="GET", path="v1/batches", query="limit=1")
    try:
        url = batch_operation_url(provider, listing)
        headers = batch_provider_headers(provider)
        _assert_secure_transport(provider, url, headers)
    except HTTPException as exc:
        return False, f"not addressable: {exc.detail}"

    try:
        async with _http_client() as client:
            response = await client.get(url, headers=headers, timeout=_BATCH_TIMEOUT)
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"

    if response.status_code < 400:
        return True, ""
    return False, f"HTTP {response.status_code}"


async def _batch_capable(provider: Dict[str, Any]) -> bool:
    """Whether this provider serves Batch, probing when the cache is cold or stale."""
    cached = provider.get("supports_batch")
    checked_at = provider.get("capability_checked_at")
    if cached is not None and isinstance(checked_at, datetime):
        age = datetime.now(timezone.utc) - checked_at.astimezone(timezone.utc)
        if age < CAPABILITY_TTL:
            return bool(cached)

    supports, detail = await probe_batch_capability(provider)
    try:
        with DBManager() as db:
            db.record_provider_batch_capability(int(provider["id"]), supports, detail)
    except Exception:  # noqa: BLE001 - a cache write must not fail the request
        logger.exception("Could not cache the Batch API capability of provider %s", provider.get("id"))
    if not supports:
        logger.info("Provider %s does not serve the Batch API (%s)", provider.get("name"), detail)
    return supports


def _header(headers: Dict[str, str], name: str) -> str:
    """A header value, read case-insensitively — Starlette lowercases names."""
    wanted = name.lower()
    for key, value in (headers or {}).items():
        if str(key).lower() == wanted:
            return (value or "").strip()
    return ""


async def resolve_batch_provider(
    auth: AuthContext, headers: Dict[str, str], db: DBManager, required: bool = True
) -> Optional[Dict[str, Any]]:
    """Pick the provider a Batch API operation is forwarded to.

    Candidates are the key's effective cloud providers that actually serve a
    Batch API. Exactly one is selected implicitly; with several the
    ``X-Logos-Provider`` header must name one. With none, ``required`` decides
    between the historical 501 and letting the caller run the batch here.
    """
    candidates = []
    for provider in db.get_batch_provider_candidates(auth.api_key_id):
        if await _batch_capable(provider):
            candidates.append(provider)

    if not candidates:
        if not required:
            return None
        raise_openai_error(
            501,
            "The OpenAI Batch API is not available for this key: none of the providers it may use " "serves one.",
            code="batch_api_not_supported",
        )

    requested = _header(headers, BATCH_PROVIDER_HEADER)
    if requested:
        matches = [
            provider
            for provider in candidates
            if str(provider["id"]) == requested or str(provider["name"]).lower() == requested.lower()
        ]
        if not matches:
            raise_openai_error(
                403,
                f"Provider {requested!r} is not one of the Batch-capable providers this key may use "
                f"({', '.join(sorted(str(p['name']) for p in candidates))}).",
                code="batch_provider_not_authorized",
            )
        return matches[0]

    if len(candidates) == 1:
        return candidates[0]

    names = ", ".join(sorted(f"{p['name']} (id {p['id']})" for p in candidates))
    raise_openai_error(
        400,
        f"This key may use several Batch-capable providers ({names}). Name one in the "
        f"{BATCH_PROVIDER_HEADER} header (provider name or id) so Logos knows where to forward.",
        code="multiple_batch_providers",
    )


async def choose_execution_target(
    auth: AuthContext,
    headers: Dict[str, str],
    db: DBManager,
    model_names: set,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Decide whether a batch is forwarded to a provider or run by Logos.

    Forwarding is preferred where it is possible, because that is the only way
    to get the provider's batch rate. It is possible only when one Batch-capable
    provider serves *every* model the file names — a provider cannot run a
    request for a model it does not host, and a batch is one job at one place.

    Everything else runs here: models served by worker nodes (which have no
    Batch API at all) and cloud models their provider does not offer for batch
    (Azure adds models to Batch long after Standard). ``X-Logos-Batch-Execution:
    logos`` forces the local path even when forwarding would work.

    Returns ``(provider or None, the key's deployments on it)``.
    """
    permitted = db.get_batch_model_deployments(auth.api_key_id)
    permitted_names = {str(row["model_name"]).lower() for row in permitted}
    unknown = sorted(name for name in model_names if name.lower() not in permitted_names)
    if unknown:
        raise_openai_error(
            403,
            f"This key may not use {', '.join(repr(name) for name in unknown)}. "
            "A batch may only request models the key is permitted to run.",
            code="model_not_permitted",
        )

    requested_execution = _header(headers, BATCH_EXECUTION_HEADER).lower()
    if requested_execution and requested_execution not in {"logos", "provider", "auto"}:
        raise_openai_error(
            400,
            f"{BATCH_EXECUTION_HEADER} must be 'auto', 'provider' or 'logos'.",
            code="invalid_request_error",
        )
    if requested_execution == "logos":
        return None, permitted

    provider = await resolve_batch_provider(auth, headers, db, required=requested_execution == "provider")
    if provider is None:
        return None, permitted

    # The provider only qualifies if it hosts every model the file names — and
    # actually batches every one of them. Hosting is the weaker half: a model
    # can be linked on the provider through a Standard deployment while the
    # provider's Batch API refuses it (Azure adds models to Batch long after
    # Standard). What the provider has refused before is tracked per model,
    # and those models count as not hosted for the choice made here.
    on_provider = [row for row in permitted if int(row["provider_id"]) == int(provider["id"])]
    hosted = {str(row["model_name"]).lower() for row in on_provider}
    model_id_by_name = {str(row["model_name"]).lower(): int(row["model_id"]) for row in on_provider}
    ineligible = db.get_batch_model_ineligibility(int(provider["id"]))
    missing = sorted(
        name for name in model_names if name.lower() not in hosted or model_id_by_name.get(name.lower()) in ineligible
    )
    if missing:
        if requested_execution == "provider" or _header(headers, BATCH_PROVIDER_HEADER):
            raise_openai_error(
                400,
                f"Provider {provider['name']!r} cannot batch {', '.join(repr(n) for n in missing)}, "
                "so it cannot run this batch. Omit the provider header to have Logos run it instead.",
                code="model_not_available_for_batch",
            )
        logger.info(
            "Running batch locally: provider %s cannot batch %s",
            provider.get("name"),
            ", ".join(missing),
        )
        return None, permitted
    return provider, on_provider


# ---------------------------------------------------------------------------
# Input file validation
# ---------------------------------------------------------------------------


def _deployment_for(provider: Optional[Dict[str, Any]], deployment_row: Dict[str, Any]) -> str:
    """What the execution target calls this model in a request body.

    Azure addresses deployments, not models, so a line that says ``gpt-4.1``
    has to leave as the deployment id the resource serves it under. A batch
    Logos runs itself keeps the Logos model name: its lines go through the
    ordinary pipeline, which does that translation per request.
    """
    if provider is None or not is_azure_provider(provider):
        return str(deployment_row["model_name"])
    return extract_azure_deployment_name(deployment_row.get("endpoint") or "") or str(deployment_row["model_name"])


def _request_endpoint(url: str) -> str:
    """The operation a request line addresses, without version or mirror prefix."""
    return strip_proxy_prefixes(str(url or "")).strip("/")


def batch_input_models(content: bytes) -> set:
    """Every model name a batch input file asks for.

    Read before the target is chosen: what the file wants decides where it can
    run.
    """
    names = set()
    for raw_line in (content or b"").splitlines():
        if not raw_line.strip():
            continue
        try:
            line = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(line, dict) and isinstance(line.get("body"), dict):
            model = line["body"].get("model")
            if isinstance(model, str) and model:
                names.add(model)
    return names


def validate_and_rewrite_batch_input(
    content: bytes,
    provider: Optional[Dict[str, Any]],
    deployments: List[Dict[str, Any]],
) -> Tuple[bytes, Dict[int, int]]:
    """Check every request line of a batch input file and retarget its model.

    Provider permission alone does not authorise what a batch runs: each line
    picks its own model, and the upstream would happily run one this key may
    not use and bill it to the shared credential. Every line is therefore
    matched against the key's permitted models, and the model name rewritten to
    what the execution target expects (an Azure deployment id when the batch is
    forwarded there; the Logos name when Logos runs it).

    Returns the rewritten file and the model-id histogram of its lines.
    """
    by_name: Dict[str, Dict[str, Any]] = {}
    for row in deployments:
        by_name.setdefault(str(row["model_name"]).lower(), row)
    rewritten_lines: List[bytes] = []
    model_counts: Dict[int, int] = {}
    seen_ids: set = set()

    for number, raw_line in enumerate(content.splitlines(), start=1):
        if not raw_line.strip():
            continue
        if len(rewritten_lines) >= MAX_BATCH_REQUESTS:
            raise_openai_error(
                400,
                f"A batch input file may hold at most {MAX_BATCH_REQUESTS} request lines.",
                code="batch_file_too_many_requests",
            )
        try:
            line = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise_openai_error(
                400, f"Line {number} of the batch file is not valid JSON: {exc}", code="invalid_batch_line"
            )
        if not isinstance(line, dict):
            raise_openai_error(400, f"Line {number} of the batch file is not a JSON object.", code="invalid_batch_line")

        custom_id = line.get("custom_id")
        if not isinstance(custom_id, str) or not custom_id:
            raise_openai_error(400, f"Line {number} of the batch file has no 'custom_id'.", code="invalid_batch_line")
        if custom_id in seen_ids:
            raise_openai_error(
                400,
                f"Line {number} repeats custom_id {custom_id!r}; each line needs its own.",
                code="invalid_batch_line",
            )
        seen_ids.add(custom_id)

        endpoint = _request_endpoint(line.get("url"))
        if endpoint not in _BATCH_REQUEST_ENDPOINTS:
            raise_openai_error(
                400,
                f"Line {number} addresses {line.get('url')!r}. Batch requests through Logos may call "
                f"{', '.join('/v1/' + name for name in sorted(_BATCH_REQUEST_ENDPOINTS))}.",
                code="unsupported_batch_endpoint",
            )

        body = line.get("body")
        if not isinstance(body, dict):
            raise_openai_error(
                400, f"Line {number} of the batch file has no request 'body'.", code="invalid_batch_line"
            )
        model = body.get("model")
        if not isinstance(model, str) or not model:
            raise_openai_error(400, f"Line {number} of the batch file names no model.", code="invalid_batch_line")

        deployment_row = by_name.get(model.lower())
        if deployment_row is None:
            raise_openai_error(
                403,
                f"Line {number} requests model {model!r}, which this key may not use"
                + (f" on provider {provider.get('name')!r}." if provider else "."),
                code="model_not_permitted",
            )

        model_id = int(deployment_row["model_id"])
        model_counts[model_id] = model_counts.get(model_id, 0) + 1
        rewritten = {**line, "body": {**body, "model": _deployment_for(provider, deployment_row)}}
        # Azure names its batch operations without the version segment; OpenAI
        # with it. Send each what it answers to, so one file works on both.
        rewritten["url"] = f"/{endpoint}" if (provider and is_azure_provider(provider)) else f"/v1/{endpoint}"
        rewritten_lines.append(json.dumps(rewritten, ensure_ascii=False).encode("utf-8"))

    if not rewritten_lines:
        raise_openai_error(400, "The batch input file holds no request lines.", code="empty_batch_file")

    return b"\n".join(rewritten_lines) + b"\n", model_counts


# ---------------------------------------------------------------------------
# Forwarding
# ---------------------------------------------------------------------------


def _upstream_response(operation: BatchOperation, resp: httpx.Response) -> Response:
    """Turn an upstream batch response into the client's response, as-is.

    The provider speaks the Batch API; its objects and errors are returned
    unmodified so OpenAI clients keep working. Only non-JSON bodies are wrapped
    in the OpenAI error shape.
    """
    if operation.resource == "files" and operation.suboperation == "content":
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/octet-stream"),
        )
    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError):
        body = None
    if isinstance(body, (dict, list)):
        return JSONResponse(content=body, status_code=resp.status_code)
    if resp.status_code < 400:
        raise_openai_error(502, "Batch API upstream returned a non-JSON response", code="batch_upstream_unreachable")
    return openai_error_response(resp.status_code, (resp.text or "Upstream error")[:500], code="upstream_error")


async def forward_batch_operation(
    provider: Dict[str, Any],
    operation: BatchOperation,
    upload: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> Response:
    """Forward one Batch API operation to the provider and pass the answer back."""
    url = batch_operation_url(provider, operation)
    headers = batch_provider_headers(provider)
    _assert_secure_transport(provider, url, headers)

    try:
        async with _http_client() as client:
            if operation.is_file_upload:
                file = upload["file"]
                data = {"purpose": upload["purpose"]}
                if upload.get("metadata"):
                    data["metadata"] = upload["metadata"]
                resp = await client.post(
                    url,
                    headers=headers,
                    data=data,
                    files=[("file", (file["filename"], file["bytes"], file["content_type"]))],
                    timeout=_BATCH_TIMEOUT,
                )
            elif json_body is not None:
                resp = await client.post(
                    url,
                    headers={**headers, "Content-Type": "application/json"},
                    json=json_body,
                    timeout=_BATCH_TIMEOUT,
                )
            else:
                # GET/DELETE, and bodyless POSTs (batch cancel): no body sent.
                resp = await client.request(operation.method, url, headers=headers, timeout=_BATCH_TIMEOUT)
    except httpx.HTTPError as exc:
        logger.error("Batch API forward to %s failed: %s: %s", url, type(exc).__name__, exc)
        raise_openai_error(
            502,
            f"Batch API upstream unreachable: {type(exc).__name__}: {exc}",
            code="batch_upstream_unreachable",
        )

    return _upstream_response(operation, resp)


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


async def _download_file(provider: Dict[str, Any], file_id: str) -> Optional[bytes]:
    """Fetch one provider-side file's content, or None when it is gone."""
    operation = BatchOperation(
        resource="files", method="GET", path=f"v1/files/{file_id}/content", resource_id=file_id, suboperation="content"
    )
    url = batch_operation_url(provider, operation)
    headers = batch_provider_headers(provider)
    _assert_secure_transport(provider, url, headers)
    try:
        async with _http_client() as client:
            resp = await client.get(url, headers=headers, timeout=_SETTLE_TIMEOUT)
    except httpx.HTTPError as exc:
        logger.warning("Could not read batch file %s: %s: %s", file_id, type(exc).__name__, exc)
        return None
    if resp.status_code >= 400:
        logger.warning("Could not read batch file %s: HTTP %s", file_id, resp.status_code)
        return None
    return resp.content


def _model_index(db: DBManager, provider: Dict[str, Any]) -> Dict[str, int]:
    """Every spelling of a model on this provider, mapped to its model id.

    The output rows name what the provider ran — an Azure deployment id, or the
    model name elsewhere — and both have to land on the Logos model whose
    prices apply.
    """
    index: Dict[str, int] = {}
    for row in db.get_provider_model_deployments(int(provider["id"])):
        model_id = int(row["model_id"])
        index[str(row["model_name"]).lower()] = model_id
        deployment = extract_azure_deployment_name(row.get("endpoint") or "")
        if deployment:
            index[deployment.lower()] = model_id
    return index


def _model_id_for(index: Dict[str, int], name: Any) -> Optional[int]:
    """Resolve a model or deployment name from a result row to a Logos model id."""
    if not isinstance(name, str) or not name:
        return None
    candidate = name.lower()
    if candidate in index:
        return index[candidate]
    # Providers append a dated version to the model they actually ran
    # (``gpt-4.1-2025-04-14``); fall back to the longest configured name that
    # prefixes it.
    matches = [key for key in index if candidate.startswith(key)]
    return index[max(matches, key=len)] if matches else None


def _usage_rows_from_output(
    content: bytes,
    owner: Dict[str, Any],
    provider: Dict[str, Any],
    model_index: Dict[str, int],
    input_models: Dict[str, str],
    logging_context: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Turn a batch output file into one usage row per finished request.

    Each row's ``request_id`` is scoped to this batch (the batch object's id,
    not the provider's id: it is the same for a settlement retry and unique
    across batches no matter what two clients call their lines). The id is
    what makes the ledger write idempotent — a settlement that is retried after
    a partial commit skips its already-booked rows on it, and two batches that
    reuse the same custom_id can no longer collide in the ledger at all.
    """
    rows: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    batch_scope = f"batch-{owner.get('id')}-"
    line_number = 0
    for raw_line in content.splitlines():
        if not raw_line.strip():
            continue
        line_number += 1
        try:
            record = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict):
            continue

        response = record.get("response") if isinstance(record.get("response"), dict) else {}
        body = response.get("body") if isinstance(response.get("body"), dict) else {}
        status_code = response.get("status_code")
        custom_id = record.get("custom_id")
        # A line without a custom_id still gets a stable identity: its position
        # in the result file, which the provider does not change.
        request_id = f"{batch_scope}{custom_id}" if isinstance(custom_id, str) else f"{batch_scope}line-{line_number}"

        usage, _ = finalize_billing_inputs({}, body, "v1/chat/completions")
        model_id = _model_id_for(model_index, body.get("model"))
        if model_id is None and isinstance(custom_id, str):
            model_id = _model_id_for(model_index, input_models.get(custom_id))

        failed = record.get("error") is not None or (isinstance(status_code, int) and status_code >= 400)
        rows.append(
            {
                "timestamp": now,
                "api_key_id": owner.get("api_key_id"),
                "team_id": owner.get("team_id"),
                "user_id": owner.get("user_id"),
                "environment": logging_context.get("environment"),
                "privacy_level": logging_context.get("log_level"),
                "provider_id": int(provider["id"]),
                "model_id": model_id,
                "request_id": request_id,
                "service_tier": "batch",
                "result_status": "error" if failed else "success",
                "error_message": json.dumps(record.get("error"))[:500] if record.get("error") else None,
                "usage": usage,
            }
        )
    return rows


def _input_model_map(content: Optional[bytes]) -> Dict[str, str]:
    """custom_id → the model name the request line asked for.

    A result row names the model the provider ran, which is usually enough; the
    input file is the exact answer for the rows where it is not (an error row
    carries no response body at all).
    """
    mapping: Dict[str, str] = {}
    if not content:
        return mapping
    for raw_line in content.splitlines():
        if not raw_line.strip():
            continue
        try:
            line = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(line, dict):
            continue
        custom_id = line.get("custom_id")
        body = line.get("body")
        if isinstance(custom_id, str) and isinstance(body, dict) and isinstance(body.get("model"), str):
            mapping[custom_id] = body["model"]
    return mapping


async def settle_batch(provider: Dict[str, Any], owner: Dict[str, Any], batch_body: Dict[str, Any]) -> int:
    """Book a finished batch's usage, exactly once.

    The provider metered the job and charged its batch rate; this brings the
    same numbers into Logos so the spend shows up under the team that ordered
    it.

    The order is what makes this safe to retry: the settlement *lease* is
    taken first (what keeps the poll path and the reconciler exclusive of each
    other), and ``settled_at`` is stamped only after the usage rows are
    durably written. A settlement that dies in between — the process exits,
    the task is cancelled — leaves the batch unsettled: the lease lapses and
    the reconciler picks the batch up again, and the idempotent ledger write
    skips whatever the first attempt already booked. Stamping first would have
    put the batch out of the reconciler's reach forever and its cost with it.
    """
    output_file_id = batch_body.get("output_file_id") or batch_body.get("error_file_id")
    with DBManager() as db:
        if not db.claim_batch_for_settlement(int(owner["id"]), SETTLEMENT_LEASE_TTL_S):
            return 0
        logging_context = (
            db.get_api_key_logging_context(int(owner["api_key_id"]))
            if owner.get("api_key_id")
            else {"log_level": "BILLING"}
        )
        model_index = _model_index(db, provider)

    if not output_file_id:
        # A batch that failed before producing any output still costs nothing;
        # close it out so it is not re-checked forever.
        logger.info("Batch %s finished without an output file; nothing to meter", owner.get("upstream_id"))
        with DBManager() as db:
            db.mark_batch_settled(int(owner["id"]))
        return 0

    try:
        output = await _download_file(provider, str(output_file_id))
        if output is None:
            raise RuntimeError("output file unreadable")
        input_models = _input_model_map(
            await _download_file(provider, str(batch_body.get("input_file_id") or owner.get("input_file_id") or ""))
            if (batch_body.get("input_file_id") or owner.get("input_file_id"))
            else None
        )
        rows = _usage_rows_from_output(output, owner, provider, model_index, input_models, logging_context)
        with DBManager() as db:
            written = db.record_batch_usage(rows)
            # Only now is the batch settled: the rows above are durably in the
            # ledger (or were already there from an earlier attempt of this
            # same settlement, which the write skips by request_id).
            db.mark_batch_settled(int(owner["id"]))
    except Exception:  # noqa: BLE001 - a failed settlement must stay retryable
        logger.exception("Settlement of batch %s failed; it will be retried", owner.get("upstream_id"))
        with DBManager() as db:
            db.release_batch_settlement(int(owner["id"]))
        return 0

    logger.info("Metered %d rows of batch %s", written, owner.get("upstream_id"))
    return written


# Background work this module starts. The event loop keeps only weak
# references to tasks, so a fire-and-forget task with no other reference can
# be garbage collected while it is still running — which would abandon a
# batch's settlement mid-download. Holding each task here until it finishes is
# the remedy the asyncio documentation recommends.
_background_tasks: set = set()


def _spawn_background(coro, what: str) -> Optional[asyncio.Task]:
    """Run a coroutine in the background, holding the task until it finishes."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no loop (sync test context): nothing can run
        coro.close()
        logger.debug("No running loop for %s", what)
        return None
    task = loop.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def _schedule_settlement(provider: Dict[str, Any], owner: Dict[str, Any], batch_body: Dict[str, Any]) -> None:
    """Settle in the background so a client's poll is not held up by it."""
    _spawn_background(settle_batch(provider, owner, batch_body), f"batch settlement of {owner.get('upstream_id')}")


# ---------------------------------------------------------------------------
# Per-model Batch eligibility, learned from the provider
# ---------------------------------------------------------------------------


def _provider_error_text(body: Dict[str, Any]) -> str:
    """The error messages a provider object or response carries, flattened."""
    error = body.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    errors = body.get("errors")
    if isinstance(errors, list):
        parts = []
        for item in errors:
            if isinstance(item, dict) and item.get("message"):
                parts.append(str(item["message"]))
            elif isinstance(item, str):
                parts.append(item)
        if parts:
            return " ".join(parts)
    return ""


def _looks_like_batch_model_error(text: str) -> bool:
    """Whether a provider error says a model cannot be batched there.

    Deliberately narrow: this text becomes a routing decision (the model's
    batches move to Logos), and an unrelated failure — a quota error, a bad
    deployment name — must not be read as "this model is not for batch".
    """
    lowered = (text or "").lower()
    return "batch" in lowered and any(marker in lowered for marker in ("not supported", "sku", "globalbatch"))


def _learn_batch_ineligibility(provider: Dict[str, Any], input_file_id: Any, error_text: str) -> None:
    """Remember, per model, that this provider refused to batch it.

    The provider does not publish which of its models it offers for batch, so
    its refusal is the only reliable source. The input file's model list (kept
    at upload) is what says which models the refused batch named: an error
    that names one of them marks just that model, and a refusal that does not
    name any marks all of them — a batch file is one job at one place, so if
    the provider could not batch the file it could not batch its models.
    """
    if not error_text or not _looks_like_batch_model_error(error_text) or not input_file_id:
        return
    try:
        with DBManager() as db:
            input_file = db.get_batch_object("file", str(input_file_id))
        if not input_file:
            return
        models = input_file.get("models")
        if not isinstance(models, list):
            return
        model_names = [name for name in models if isinstance(name, str)]
        if not model_names:
            return
        lowered = error_text.lower()
        targets = [name for name in model_names if name.lower() in lowered] or model_names
        with DBManager() as db:
            index = {
                str(row["model_name"]).lower(): int(row["model_id"])
                for row in db.get_provider_model_deployments(int(provider["id"]))
            }
            for name in targets:
                model_id = index.get(name.lower())
                if model_id is not None:
                    db.record_model_batch_ineligibility(int(provider["id"]), model_id, error_text[:400])
        logger.info(
            "Provider %s refused to batch %s; that model's batches will run in Logos",
            provider.get("name"),
            ", ".join(targets),
        )
    except Exception:  # noqa: BLE001 - learning must never break the request path
        logger.exception("Could not record Batch ineligibility on provider %s", provider.get("id"))


async def reconcile_batches_once() -> int:
    """Settle every finished batch nobody polled to completion.

    A client is free to fire a batch and never come back; without this its cost
    would never be booked.
    """
    settled = 0
    with DBManager() as db:
        pending = db.get_unsettled_batches()
        providers = {
            provider_id: db.get_batch_provider(provider_id) for provider_id in {row["provider_id"] for row in pending}
        }

    for owner in pending:
        provider = providers.get(owner["provider_id"])
        if not provider:
            _rotate_unsettled_batch_out_of_the_window(owner)
            continue
        operation = BatchOperation(
            resource="batches",
            method="GET",
            path=f"v1/batches/{owner['upstream_id']}",
            resource_id=str(owner["upstream_id"]),
        )
        try:
            response = await forward_batch_operation(provider, operation)
        except HTTPException:
            _rotate_unsettled_batch_out_of_the_window(owner)
            continue
        body = _response_json(response) or {}
        status = body.get("status")
        with DBManager() as db:
            db.record_batch_provider_state(str(owner["upstream_id"]), body)
        if status in TERMINAL_BATCH_STATES:
            if status == "failed":
                # The unsettled-batches query does not carry the input file id,
                # so take it from the provider's answer, as settlement does —
                # otherwise a failure nobody polled could never teach.
                input_file_id = body.get("input_file_id") or owner.get("input_file_id")
                _learn_batch_ineligibility(provider, input_file_id, _provider_error_text(body))
            settled += await settle_batch(provider, owner, body)
    return settled


def _rotate_unsettled_batch_out_of_the_window(owner: Dict[str, Any]) -> None:
    """Mark an uncheckable batch as seen, so the window can move on.

    The unsettled-batches window leads with the least recently checked. A
    batch whose check could not run — its provider row is gone, or the
    upstream refused the call — must not keep its place in it, or every
    batch behind it waits on every pass.
    """
    try:
        with DBManager() as db:
            db.update_batch_object_status(str(owner["upstream_id"]), None)
    except Exception:  # noqa: BLE001 - the next pass simply takes the same window
        logger.debug("Could not rotate unsettled batch %s out of the window", owner.get("upstream_id"))


async def batch_reconciler_loop() -> None:
    """Periodically settle batches that finished while nobody was polling."""
    while True:
        try:
            await asyncio.sleep(RECONCILE_INTERVAL_S)
            await reconcile_batches_once()
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:  # noqa: BLE001 - the loop outlives its failures
            logger.exception("Batch reconciliation pass failed")


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


def _owns_object(auth: AuthContext, owned: Dict[str, Any]) -> bool:
    """Whether this caller's principal owns the object's row.

    A team's objects belong to the team; an object a team-less key created
    belongs to that user alone, and to the key itself when even the user is
    absent. Comparing team ids alone is not a scope: personal keys carry
    ``team_id = NULL``, and ``NULL == NULL`` would make every unteamed key on
    the instance the owner of every other one's batches and their output
    files.
    """
    if auth.team_id is not None:
        return owned.get("team_id") == auth.team_id
    if owned.get("team_id") is not None:
        return False
    if auth.user_id is not None:
        return owned.get("user_id") == auth.user_id
    return owned.get("api_key_id") == auth.api_key_id


def _owned_or_404(db: DBManager, auth: AuthContext, operation: BatchOperation) -> Dict[str, Any]:
    """The ownership row for the addressed id, or a 404 if it isn't the caller's.

    An id another principal owns is answered exactly like one that never
    existed: saying it exists would already leak that someone else is running
    it.
    """
    kind = "file" if operation.resource == "files" else "batch"
    owned = db.get_batch_object(kind, str(operation.resource_id))
    if owned is None or not _owns_object(auth, owned):
        raise_openai_error(404, f"No such {kind}: {operation.resource_id!r}.", code="not_found")
    return owned


def _response_json(response: Response) -> Optional[Dict[str, Any]]:
    body = getattr(response, "body", None)
    if not isinstance(body, (bytes, bytearray)):
        return None
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _listing_response(db: DBManager, auth: AuthContext, operation: BatchOperation) -> Response:
    """List the caller's own objects (team, else user, else key), from Logos' record.

    Not forwarded: the shared upstream credential sees every team's objects,
    and Logos minted all of its own — so its record is both the safe answer and
    the complete one, covering batches it ran itself that no provider knows.
    """
    kind = "file" if operation.resource == "files" else "batch"
    rows = db.list_batch_objects_for_principal(kind, auth.team_id, auth.user_id, auth.api_key_id)
    data = [
        (
            (local_file_object(row) if kind == "file" else local_batch_object(row))
            if row.get("execution") == "logos"
            else _remote_object_summary(row, kind)
        )
        for row in rows
    ]
    return JSONResponse(
        content={
            "object": "list",
            "data": data,
            "has_more": False,
            "first_id": data[0]["id"] if data else None,
            "last_id": data[-1]["id"] if data else None,
        }
    )


def _remote_object_summary(row: Dict[str, Any], kind: str) -> Dict[str, Any]:
    """What Logos knows about an object the provider holds.

    A listing reports the last poll's view — status, and for a batch its
    result file and running counts, stored with the status when the provider
    last answered for it; retrieving the object individually asks the
    provider and is authoritative.
    """
    created_at = row.get("created_at")
    summary = {
        "id": row.get("upstream_id"),
        "object": kind,
        "created_at": int(created_at.timestamp()) if isinstance(created_at, datetime) else None,
        "logos_execution": "provider",
        "logos_provider_id": row.get("provider_id"),
    }
    if kind == "batch":
        summary["status"] = row.get("status")
        summary["input_file_id"] = row.get("input_file_id")
        # Without these a finished provider batch would never show its result
        # download and a running one its progress: the listing does not ask
        # the provider for each row, it renders what the last poll stored.
        summary["output_file_id"] = row.get("output_file_id")
        summary["error_file_id"] = row.get("error_file_id")
        summary["request_counts"] = {
            "total": int(row.get("total_requests") or 0),
            "completed": int(row.get("completed_requests") or 0),
            "failed": int(row.get("failed_requests") or 0),
        }
    return summary


# ---------------------------------------------------------------------------
# Serving a batch Logos runs itself
# ---------------------------------------------------------------------------


def _serve_local_operation(db: DBManager, operation: BatchOperation, owner: Dict[str, Any]) -> Response:
    """Answer a lifecycle call for an object Logos holds."""
    if operation.resource == "batches":
        if operation.suboperation == "cancel":
            db.request_local_batch_cancel(int(owner["id"]))
            refreshed = db.get_local_batch(str(owner["upstream_id"])) or owner
            return JSONResponse(content=local_batch_object(refreshed))
        return JSONResponse(content=local_batch_object(owner))

    if operation.suboperation == "content":
        content = db.get_local_batch_file_content(int(owner["id"]))
        if content is None:
            raise_openai_error(404, f"No content for file {owner['upstream_id']!r}.", code="not_found")
        return Response(content=content, media_type="application/jsonl")

    if operation.method == "DELETE":
        # The runner reads the input's bytes when it starts the batch, not
        # when the batch is created. Deleting a file a not-yet-finished batch
        # still references would strand that batch: it would find no content
        # and fail one it was accepted to run, so the delete is refused until
        # every referencing batch is terminal.
        if db.count_nonterminal_batches_for_input_file(str(owner["upstream_id"])) > 0:
            raise_openai_error(
                409,
                f"File {owner['upstream_id']!r} is still the input of a batch that has not finished; "
                "it can be deleted once that batch is done.",
                code="batch_input_file_in_use",
            )
        db.delete_batch_object(int(owner["id"]))
        return JSONResponse(content={"id": owner["upstream_id"], "object": "file", "deleted": True})

    return JSONResponse(content=local_file_object(owner))


def _start_local_batch(batch_row: Dict[str, Any]) -> None:
    """Kick a freshly created batch off now instead of waiting for the poller."""
    _spawn_background(run_local_batch(batch_row), f"local batch {batch_row.get('upstream_id')}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _finalize_batch_log(
    log_id: Optional[int],
    *,
    provider_id: Optional[int],
    result_status: str,
    error_message: Optional[str] = None,
) -> None:
    """Close out the usage-log row a batch *operation* opened.

    This row records the control-plane call (upload, create, poll), not the
    work: a forwarded batch's tokens are booked when its result file is read,
    and a Logos-run batch's are booked request by request as it runs.
    """
    if not log_id:
        return
    now = datetime.now(timezone.utc)
    try:
        with DBManager() as db:
            db.update_log_entry_metrics(
                log_id=log_id,
                provider_id=provider_id,
                result_status=result_status,
                error_message=error_message,
                scheduled_ts=now,
                request_complete_ts=now,
            )
    except Exception:  # noqa: BLE001 - logging must never break the forward
        logger.exception("Failed to finalise Batch API log entry %s", log_id)


async def _read_json_body(request: Request) -> Dict[str, Any]:
    try:
        json_body = await request.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if json_body is None:
        return {}
    if not isinstance(json_body, dict):
        raise HTTPException(status_code=400, detail="JSON payload must be an object")
    return json_body


def _check_batch_budget(db: DBManager, auth: AuthContext) -> None:
    """A key already over its monthly budget does not get to start more work.

    The batch's own cost lands when it finishes, so this is the same guard the
    request pipeline applies, not a forecast.
    """
    check_monthly_budget(db, auth, True, datetime.now(timezone.utc).date().replace(day=1).isoformat())


async def _handle_file_upload(request: Request, auth: AuthContext, headers: Dict[str, str], db: DBManager):
    """Validate an input file, choose where it will run, and put it there.

    Returns ``(response_or_None, forward_args, log_payload)``: a response when
    Logos stored the file itself, otherwise what the forward needs.
    """
    upload = await parse_batch_file_upload(request)
    raw = upload["file"]["bytes"]
    provider, deployments = await choose_execution_target(auth, headers, db, batch_input_models(raw))
    rewritten, model_counts = validate_and_rewrite_batch_input(raw, provider, deployments)
    log_payload = {
        "purpose": upload["purpose"],
        "filename": upload["file"]["filename"],
        "size": len(rewritten),
        "requests": sum(model_counts.values()),
        "model_ids": sorted(model_counts),
        "models": sorted(str(row["model_name"]) for row in deployments if int(row["model_id"]) in model_counts),
        "execution": "provider" if provider else "logos",
    }

    if provider is not None:
        upload = {**upload, "file": {**upload["file"], "bytes": rewritten}}
        return None, (provider, upload), log_payload

    file_id = new_object_id("file")
    db.store_local_batch_file(
        upstream_id=file_id,
        content=rewritten,
        filename=upload["file"]["filename"],
        api_key_id=auth.api_key_id,
        team_id=auth.team_id,
        user_id=auth.user_id,
    )
    stored = db.get_local_object_by_upstream_id("file", file_id)
    return JSONResponse(content=local_file_object(stored)), None, log_payload


def _assert_still_permitted(
    db: DBManager, auth: AuthContext, provider: Dict[str, Any], input_file: Dict[str, Any]
) -> None:
    """The key that creates the batch may still use what the file lives on.

    Ownership says who may order the job — the team. It does not say what the
    creating key may still run: permissions can be key-specific, and they can
    move after the upload. Without this re-check a narrower team key — or the
    uploading key after its links were revoked — would run the file's
    previously authorised models through the shared provider credential. Both
    halves are therefore asked again at creation: the provider the file lives
    on, and every model the file row recorded.
    """
    candidates = db.get_batch_provider_candidates(auth.api_key_id)
    if not any(int(row["id"]) == int(provider["id"]) for row in candidates):
        raise_openai_error(
            403,
            f"This key may no longer use provider {provider.get('name')!r}, which holds this file.",
            code="batch_provider_not_authorized",
        )
    permitted = {str(row["model_name"]).lower() for row in db.get_batch_model_deployments(auth.api_key_id)}
    missing = sorted(str(name) for name in (input_file.get("models") or []) if str(name).lower() not in permitted)
    if missing:
        raise_openai_error(
            403,
            f"This key may not use {', '.join(repr(name) for name in missing)}: the file asks for "
            "models the key no longer may run.",
            code="model_not_permitted",
        )


def _local_batch_contract(content: bytes, json_body: Dict[str, Any]) -> str:
    """The contract a locally-run batch keeps with its stored lines, or a 400.

    The provider enforces this contract for the batches it runs and refuses
    the rest, so a batch Logos runs itself is held to the same one before it
    exists: one supported endpoint, the one completion window, and every
    stored line a POST to exactly that endpoint — because the runner executes
    the lines' own urls while the batch object advertises the endpoint it was
    created with. Returns the endpoint to store on the batch.
    """
    endpoint = str(json_body.get("endpoint") or "/v1/chat/completions")
    wanted = _request_endpoint(endpoint)
    if wanted not in _BATCH_REQUEST_ENDPOINTS:
        raise_openai_error(
            400,
            f"Batch endpoint {endpoint!r} is not supported. Batches through Logos may call "
            f"{', '.join('/v1/' + name for name in sorted(_BATCH_REQUEST_ENDPOINTS))}.",
            code="unsupported_batch_endpoint",
        )
    if json_body.get("completion_window") != "24h":
        raise_openai_error(400, "completion_window must be '24h'.", code="invalid_request_error")

    for number, line in enumerate(parse_request_lines(content), start=1):
        method = line.get("method")
        if method is not None and str(method).upper() != "POST":
            raise_openai_error(
                400,
                f"Line {number} uses method {method!r}; batch lines are POST requests.",
                code="invalid_batch_line",
            )
        if _request_endpoint(line.get("url")) != wanted:
            raise_openai_error(
                400,
                f"Line {number} addresses {line.get('url')!r}, but the batch is {endpoint!r}: every "
                "line of a batch must call the endpoint the batch was created with.",
                code="invalid_batch_line",
            )
    return f"/v1/{wanted}"


async def _handle_batch_creation(json_body: Dict[str, Any], auth: AuthContext, db: DBManager):
    """Authorise a batch and either create it here or hand it to the provider."""
    input_file_id = json_body.get("input_file_id")
    if not isinstance(input_file_id, str) or not input_file_id:
        raise_openai_error(400, "A batch needs an 'input_file_id'.", code="invalid_request_error")
    input_file = db.get_batch_object("file", input_file_id)
    if input_file is None or not _owns_object(auth, input_file):
        raise_openai_error(404, f"No such file: {input_file_id!r}.", code="not_found")

    _check_batch_budget(db, auth)

    if input_file.get("execution") != "logos":
        provider = db.get_batch_provider(int(input_file["provider_id"]))
        if provider is None:
            raise_openai_error(502, "The provider holding this file is gone.", code="batch_upstream_unreachable")
        _assert_still_permitted(db, auth, provider, input_file)
        return None, provider

    content = db.get_local_batch_file_content(int(input_file["id"])) or b""
    endpoint = _local_batch_contract(content, json_body)
    batch_id = new_object_id("batch")
    db.create_local_batch(
        upstream_id=batch_id,
        input_file_id=input_file_id,
        endpoint=endpoint,
        completion_window="24h",
        metadata=json_body.get("metadata") if isinstance(json_body.get("metadata"), dict) else None,
        total_requests=len(parse_request_lines(content)),
        api_key_id=auth.api_key_id,
        team_id=auth.team_id,
        user_id=auth.user_id,
    )
    created = db.get_local_batch(batch_id)
    _start_local_batch(created)
    return JSONResponse(content=local_batch_object(created)), None


async def _rerun_refused_creation_locally(
    provider: Dict[str, Any], json_body: Dict[str, Any], auth: AuthContext
) -> Optional[JSONResponse]:
    """Run a refused batch creation here, from the file the provider holds.

    Auto mode means "forward when that can work". A creation the provider
    refused with a model-availability error has just said it cannot, so the
    batch is created locally from the same input instead of the refusal being
    the answer: the first request still ends in a batch, and the ineligibility
    recorded alongside this rerun routes the next upload of the file locally
    on its own.
    """
    input_file_id = json_body.get("input_file_id")
    content = await _download_file(provider, str(input_file_id))
    if content is None:
        return None
    # The provider holds the file as Logos uploaded it, i.e. with the model
    # spellings the provider's deployments use. The local pipeline wants Logos
    # model names, so those spellings are translated back on the way in.
    with DBManager() as db:
        deployments = db.get_provider_model_deployments(int(provider["id"]))
    name_by_deployment = {str(_deployment_for(provider, row)).lower(): str(row["model_name"]) for row in deployments}
    lines: List[bytes] = []
    for raw_line in content.splitlines():
        if not raw_line.strip():
            continue
        try:
            line = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(line, dict) and isinstance(line.get("body"), dict):
            model = line["body"].get("model")
            if isinstance(model, str) and model.lower() in name_by_deployment:
                line["body"]["model"] = name_by_deployment[model.lower()]
        lines.append(json.dumps(line, ensure_ascii=False).encode("utf-8"))
    if not lines:
        return None
    stored = b"\n".join(lines) + b"\n"
    try:
        endpoint = _local_batch_contract(stored, json_body)
    except HTTPException:
        # The rerun is the alternative to the provider's refusal, not a
        # rewrite of it: an input that no longer keeps the batch contract
        # leaves the refusal standing. Checked before anything is stored, so
        # a refusal here orphans no file.
        return None
    file_id = new_object_id("file")
    batch_id = new_object_id("batch")
    with DBManager() as db:
        db.store_local_batch_file(
            upstream_id=file_id,
            content=stored,
            filename=f"{input_file_id}_rerun.jsonl",
            api_key_id=auth.api_key_id,
            team_id=auth.team_id,
            user_id=auth.user_id,
        )
        db.create_local_batch(
            upstream_id=batch_id,
            input_file_id=file_id,
            endpoint=endpoint,
            completion_window="24h",
            metadata=json_body.get("metadata") if isinstance(json_body.get("metadata"), dict) else None,
            total_requests=len(parse_request_lines(stored)),
            api_key_id=auth.api_key_id,
            team_id=auth.team_id,
            user_id=auth.user_id,
        )
        created = db.get_local_batch(batch_id)
    if created is None:
        return None
    _start_local_batch(created)
    return JSONResponse(content=local_batch_object(created))


async def handle_batch_api_request(request: Request) -> Response:
    """Authenticate, authorise, run or forward, and account for one operation.

    Entry point for every files/batches route and its mirrors.
    """
    operation = parse_batch_api_path(request.url.path, method=request.method, query=request.url.query)
    if operation is None:
        raise_openai_error(404, f"No Batch API route at {request.url.path!r}", code="unknown_batch_route")

    headers = dict(request.headers)
    # The Batch API — and only it — resolves the scoped credential; every
    # other route authenticates with key values alone.
    auth = authenticate_batch_api_key(headers)

    request_id = secrets.token_urlsafe(16)
    log_id: Optional[int] = None
    provider: Optional[Dict[str, Any]] = None
    owner: Optional[Dict[str, Any]] = None
    upload: Optional[Dict[str, Any]] = None
    json_body: Optional[Dict[str, Any]] = None
    log_payload: Dict[str, Any] = {}
    response: Optional[Response] = None

    try:
        with DBManager() as db:
            if operation.resource_id:
                owner = _owned_or_404(db, auth, operation)

            # Bodies are read after the caller is known to be entitled to the
            # operation, so an unauthorised request cannot spend the upload
            # budget.
            if operation.is_file_upload:
                response, forward_args, log_payload = await _handle_file_upload(request, auth, headers, db)
                if forward_args:
                    provider, upload = forward_args
            elif operation.is_batch_creation:
                json_body = await _read_json_body(request)
                log_payload = dict(json_body)
                response, provider = await _handle_batch_creation(json_body, auth, db)
            elif operation.is_listing:
                response = _listing_response(db, auth, operation)
            elif owner is not None and owner.get("execution") == "logos":
                response = _serve_local_operation(db, operation, owner)
            elif owner is not None:
                provider = db.get_batch_provider(int(owner["provider_id"]))
                if provider is None:
                    raise_openai_error(
                        502, "The provider holding this object is gone.", code="batch_upstream_unreachable"
                    )

            r_log, c_log = db.log_usage(
                api_key_id=auth.api_key_id,
                team_id=auth.team_id,
                user_id=auth.user_id,
                environment=auth.environment,
                log_level=auth.log_level,
                client_ip=get_client_ip(request),
                input_payload=log_payload,
                headers=sanitized_headers_for_persistence(headers),
                request_id=request_id,
            )
            log_id = int(r_log["log-id"]) if c_log == 200 else None

        if response is None:
            response = await forward_batch_operation(provider, operation, upload, json_body)
            response = await _register_upstream_object(
                response, operation, provider, auth, owner, file_models=log_payload.get("models")
            )
            # A file the provider actually deleted is gone from Logos's books
            # as well: the ownership row would keep the dead id in the listing,
            # and a later creation naming it would pass the local ownership
            # check and only fail upstream.
            if (
                operation.method == "DELETE"
                and owner is not None
                and owner.get("execution") == "provider"
                and response.status_code < 400
            ):
                with DBManager() as db:
                    db.delete_batch_object(int(owner["id"]))
    except HTTPException as exc:
        _finalize_batch_log(
            log_id,
            provider_id=provider.get("id") if provider else None,
            result_status="error",
            error_message=str(exc.detail),
        )
        raise

    provider_id = provider.get("id") if provider else None
    if response.status_code < 400:
        _finalize_batch_log(log_id, provider_id=provider_id, result_status="success")
    else:
        payload = _response_json(response) or {}
        error_text = ""
        if isinstance(payload.get("error"), dict):
            error_text = str(payload["error"].get("message") or "")
        _finalize_batch_log(
            log_id,
            provider_id=provider_id,
            result_status="error",
            error_message=error_text or f"Batch API upstream returned {response.status_code}",
        )
        # A creation refused because one of the file's models is not batchable
        # is the one refusal that teaches Logos to route that model locally
        # from now on, instead of failing the same way on the next file.
        if (
            operation.is_batch_creation
            and provider is not None
            and isinstance(json_body, dict)
            and json_body.get("input_file_id")
        ):
            _learn_batch_ineligibility(provider, json_body.get("input_file_id"), error_text)
            # In auto mode only the model-availability refusal is not the
            # answer: the provider just said it cannot batch this file's
            # models, so the same file is run here instead, and the first
            # request still ends in a batch. Every other refusal — a quota,
            # a window, an upstream of its own — is the provider's answer,
            # not a reason to re-run the job locally, so the same gate that
            # limits the learning limits the rerun. A provider that was
            # named or forced keeps the refusal — that is what it asked for.
            execution = _header(headers, BATCH_EXECUTION_HEADER).lower()
            if (
                _looks_like_batch_model_error(error_text)
                and execution not in {"provider", "logos"}
                and not _header(headers, BATCH_PROVIDER_HEADER)
            ):
                rerun = await _rerun_refused_creation_locally(provider, json_body, auth)
                if rerun is not None:
                    return rerun
    return response


async def _record_upstream_object(db: DBManager, register_kwargs: Dict[str, Any]) -> None:
    """Commit one ownership row, retrying the write.

    The provider has already created the object when this runs, so a
    transient database failure must not turn into "the object exists upstream
    but nobody at Logos knows who owns it" — that orphan is both unreachable
    for its owner and invisible to the settlement path. A few short retries
    ride out the transient case; what survives them is handled by the caller,
    which removes the provider object again.
    """
    last: Optional[Exception] = None
    for attempt in range(3):
        try:
            db.register_batch_object(**register_kwargs)
            return
        except Exception as exc:  # noqa: BLE001 - the retries are the handling
            last = exc
            # A failed write leaves the shared session in an aborted
            # transaction; without a rollback the next attempt would raise
            # PendingRollbackError instead of retrying the write.
            try:
                db.session.rollback()
            except Exception:  # noqa: BLE001 - the retry (or the raise) reports the state
                pass
            await asyncio.sleep(0.2 * (attempt + 1))
    assert last is not None
    raise last


async def _remove_upstream_object(provider: Dict[str, Any], operation: BatchOperation, upstream_id: str) -> None:
    """Best effort: undo what the provider just minted, so an unowned object does not linger there.

    Files are deleted; a batch job is *cancelled*. The OpenAI Batch API has no
    delete operation — the only way to stop a job is ``POST /v1/batches/{id}/cancel`` —
    and a DELETE there comes back 405, which would leave the job running (and
    billing under the shared credential) with nobody at Logos to account for it.
    """
    if operation.resource == "batches":
        cleanup = BatchOperation(
            resource="batches",
            method="POST",
            path=f"v1/batches/{upstream_id}/cancel",
            resource_id=upstream_id,
            suboperation="cancel",
        )
    else:
        cleanup = BatchOperation(
            resource="files",
            method="DELETE",
            path=f"v1/files/{upstream_id}",
            resource_id=upstream_id,
        )
    try:
        await forward_batch_operation(provider, cleanup)
        verb = "cancelled" if operation.resource == "batches" else "removed"
        logger.warning("%s upstream %s %s whose ownership could not be recorded", verb, operation.resource, upstream_id)
    except Exception:  # noqa: BLE001 - the error below already says what happened
        logger.exception("Could not remove upstream %s %s", operation.resource, upstream_id)


async def _register_upstream_object(
    response: Response,
    operation: BatchOperation,
    provider: Dict[str, Any],
    auth: AuthContext,
    owner: Optional[Dict[str, Any]],
    file_models: Optional[List[str]] = None,
) -> Response:
    """Record what the provider just minted, and settle a batch that finished.

    For the operations that mint something new (a file upload, a batch
    creation) the response is not returned before the ownership row is
    durable: with the provider credential shared by every key allowed to use
    the provider, an object without an owner is an object anyone could later
    fail to reach or — worse, if the row were simply skipped — an object any
    key could use. When the row cannot be committed the provider object is
    removed again and the caller gets an error, so the provider never holds
    what Logos cannot account for.
    """
    if response.status_code >= 400:
        return response
    payload = _response_json(response)
    if payload is None:
        return response

    upstream_id = payload.get("id")
    if operation.is_file_upload and isinstance(upstream_id, str):
        register_kwargs = dict(
            kind="file",
            upstream_id=upstream_id,
            provider_id=int(provider["id"]),
            api_key_id=auth.api_key_id,
            team_id=auth.team_id,
            user_id=auth.user_id,
            models=file_models,
        )
        try:
            with DBManager() as db:
                await _record_upstream_object(db, register_kwargs)
        except Exception:  # noqa: BLE001 - see the error below for the outcome
            logger.exception("Could not record ownership of upstream file %s", upstream_id)
            await _remove_upstream_object(provider, operation, upstream_id)
            raise_openai_error(
                502,
                "The provider created the file, but Logos could not record who owns it and "
                "removed it again. Try the upload once more.",
                code="batch_ownership_unrecorded",
            )
    elif operation.is_batch_creation and isinstance(upstream_id, str):
        register_kwargs = dict(
            kind="batch",
            upstream_id=upstream_id,
            provider_id=int(provider["id"]),
            api_key_id=auth.api_key_id,
            team_id=auth.team_id,
            user_id=auth.user_id,
            input_file_id=payload.get("input_file_id"),
            status=payload.get("status"),
        )
        try:
            with DBManager() as db:
                await _record_upstream_object(db, register_kwargs)
        except Exception:  # noqa: BLE001 - see the error below for the outcome
            logger.exception("Could not record ownership of upstream batch %s", upstream_id)
            await _remove_upstream_object(provider, operation, upstream_id)
            raise_openai_error(
                502,
                "The provider created the batch, but Logos could not record who owns it and "
                "removed it again. Try the creation once more.",
                code="batch_ownership_unrecorded",
            )
    elif operation.resource == "batches" and operation.resource_id and owner is not None:
        # Polling: nothing new to own, and a failure here is retried by the
        # next poll and by the reconciler, so it must not turn a successful
        # upstream poll into a 500.
        status = payload.get("status")
        try:
            with DBManager() as db:
                db.record_batch_provider_state(str(operation.resource_id), payload)
                # A terminal response is what names the result file (and the
                # error file). Register both for the batch's owner now: they
                # appear in the provider's list for every key that may use the
                # provider, and without a row of their own the owner's result
                # download would be a 404 while a stranger's would work.
                for file_field in ("output_file_id", "error_file_id"):
                    file_id = payload.get(file_field)
                    if isinstance(file_id, str) and file_id:
                        db.register_batch_object(
                            kind="file",
                            upstream_id=file_id,
                            provider_id=int(provider["id"]),
                            api_key_id=owner.get("api_key_id"),
                            team_id=owner.get("team_id"),
                            user_id=owner.get("user_id"),
                        )
            if status == "failed":
                _learn_batch_ineligibility(provider, owner.get("input_file_id"), _provider_error_text(payload))
        except Exception:  # noqa: BLE001 - the next poll (and the reconciler) retries this
            logger.exception("Could not update the state of batch %s", operation.resource_id)
        if status in TERMINAL_BATCH_STATES and owner.get("settled_at") is None:
            _schedule_settlement(provider, owner, payload)

    return response
