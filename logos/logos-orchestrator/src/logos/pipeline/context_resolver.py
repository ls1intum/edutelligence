# src/logos/pipeline/context_resolver.py
"""
Context resolution - prepares execution inputs from database lookups.

Separates the "what to execute" (context resolution) from "how to execute" (executor).
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qsl, urlencode

from logos.dbutils.dbmanager import DBManager
from logos.logosnode_registry import LogosNodeRuntimeRegistry
from logos.pipeline.effort_normalization import normalize_reasoning_effort
from logos.request_content import is_multipart_payload, set_payload_field
from logos.sdi.azure_deployment_sync import AZURE_OPERATION_API_VERSIONS

logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Everything needed to execute a request - resolved from DB."""

    model_id: int
    provider_id: int
    provider_name: str
    provider_type: str
    forward_url: str
    auth_header: str
    auth_value: str
    model_name: str
    lane_id: Optional[str] = None
    # Set for Azure Responses-API routes: the deployment id the request body's
    # "model" field must be rewritten to (Azure /responses resolves the
    # deployment from the body, not the URL). See ``_azure_responses_route``.
    azure_responses_deployment: Optional[str] = None


class ContextResolver:
    """
    Resolves execution context from database.

    Responsibilities:
    - Look up model/provider/API key from DB
    - Construct forward URL and auth headers
    - Return all info needed for HTTP execution

    NOT responsible for:
    - Making HTTP calls (that's the Executor's job)
    """

    def __init__(
        self,
        logosnode_registry: Optional[LogosNodeRuntimeRegistry] = None,
        lane_preparer: Optional[Any] = None,
    ):
        self._logosnode_registry = logosnode_registry
        self._lane_preparer = lane_preparer

    async def resolve_context(
        self,
        model_id: int,
        provider_id: int,
        request_path: Optional[str] = None,
    ) -> Optional[ExecutionContext]:
        """
        Resolve all DB information needed to execute a request with authorization verification.

        This includes:
        - Model endpoint and configuration
        - Provider base URL and type
        - API key for the specific model/provider pair
        - Authorization check (if logos_key and profile_id provided)

        Args:
            model_id: The ID of the model to execute.
            provider_id: The ID of the provider (currently unused, for future extension)
            logos_key: User's logos key (for authorization check)
            profile_id: Profile ID (for authorization check)

        Returns:
            `ExecutionContext` with all details, or `None` if resolution fails (e.g. missing key, unauthorized).
        """
        with DBManager() as db:
            auth_info = db.get_auth_info_to_deployment(model_id, provider_id)
            if not auth_info:
                logger.error(f"No deployment auth info for model={model_id}, provider={provider_id}")
                return None

            provider_type_raw = (auth_info.get("provider_type") or "").lower()
            provider_type = (
                "logosnode"
                if provider_type_raw
                in {
                    "logosnode",
                    "node",
                    "node_controller",
                    "ollama",
                    "logos_worker_node",
                }
                else provider_type_raw
            )
            auth_name = (auth_info.get("auth_name") or "").strip()
            auth_format = auth_info.get("auth_format") or ""
            api_key = auth_info.get("api_key")

            # The provider form advertises "Authorization" and "Bearer {}" as
            # placeholders, so operators routinely save an OpenAI-shaped cloud
            # provider with both fields empty. Without a default the header was
            # dropped silently below and the upstream rejected the request as
            # unauthenticated — apply the advertised convention instead. An
            # explicit header name (e.g. Azure's "api-key") keeps its own name
            # and defaults to the bare key rather than a Bearer prefix.
            if provider_type != "logosnode" and api_key:
                if not auth_name:
                    auth_name = "Authorization"
                    auth_format = auth_format or "Bearer {}"
                elif not auth_format:
                    auth_format = "{}"

            if provider_type != "logosnode" and not api_key and (auth_name or auth_format):
                logger.error(
                    f"No API key for model {model_id} / provider {auth_info.get('provider_name', provider_id)}"
                )
                return None

        provider_name = auth_info["provider_name"]
        model_name = auth_info["model_name"]
        endpoint = auth_info["endpoint"]
        base_url = auth_info["base_url"]
        lane_id: Optional[str] = None
        azure_responses_deployment: Optional[str] = None

        if provider_type == "logosnode":
            prepared_lane: Optional[Dict[str, Any]] = None
            if self._lane_preparer is not None:
                try:
                    prepared_lane = await self._lane_preparer.prepare_lane_for_request(
                        provider_id,
                        model_name,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Request-time lane preparation failed for provider=%s model=%s: %s",
                        provider_name,
                        model_name,
                        exc,
                    )
            if self._logosnode_registry is not None:
                lane = prepared_lane
                if lane is None:
                    lane = await self._logosnode_registry.select_lane_for_model(provider_id, model_name)
                # Retry loop: lane may be transitioning (loading/waking) after
                # reevaluate_model_queues dispatched us.
                if lane is None:
                    # Retry up to ~120s — must survive worst-case multi-lane
                    # drain (busy vLLM lanes with continuous batching can have
                    # 10-20 active requests that must finish before sleep) plus
                    # sleep/wake cycle (~5s).  First 10 retries are 1s apart
                    # (fast path); remaining retries back off to 2s.
                    for attempt in range(65):
                        await asyncio.sleep(1.0 if attempt < 10 else 2.0)
                        lane = await self._logosnode_registry.select_lane_for_model(provider_id, model_name)
                        if lane is not None:
                            logger.info(
                                "Lane became available after %ds for provider=%s model=%s",
                                attempt + 1,
                                provider_name,
                                model_name,
                            )
                            break
                if lane is not None:
                    lane_id = str(lane.get("lane_id", "")).strip()
                    if lane_id:
                        forward_url = f"logosnode://provider/{provider_id}/lane/{lane_id}"
                    else:
                        logger.error(
                            "logosnode lane missing lane_id for provider=%s",
                            provider_name,
                        )
                        return None
                else:
                    logger.warning(
                        "No logosnode lane available for provider=%s model=%s after retries",
                        provider_name,
                        model_name,
                    )
                    return None
            else:
                logger.error(
                    "logosnode registry unavailable for provider=%s model=%s; cannot resolve execution without a lane",
                    provider_name,
                    model_name,
                )
                return None
        elif provider_type == "cloud":
            # Cloud upstream serves the same OpenAI-shaped surface as our /v1
            # (and /v2) routes, so forward like-for-like on the inbound path.
            # Auth comes from the DB (auth_name / auth_format / api_key) like
            # every other non-logosnode provider.
            forward_url = self._cloud_forward_url(base_url, request_path, endpoint)
            # Azure Responses deployments are stored deployment-scoped
            # (.../deployments/<id>/responses) so the id survives into here;
            # collapse to Azure's real /openai/responses route and remember the
            # id so the body "model" can be rewritten to it at forward time.
            responses_url, responses_deployment = self._azure_responses_route(forward_url)
            if responses_url is not None:
                forward_url = responses_url
                azure_responses_deployment = responses_deployment
        else:
            forward_url = self._merge_url(base_url, endpoint)

        return ExecutionContext(
            model_id=model_id,
            provider_id=provider_id,
            provider_name=provider_name,
            provider_type=provider_type,
            forward_url=forward_url,
            auth_header=auth_name,
            auth_value=auth_format.format(api_key or ""),
            model_name=model_name,
            lane_id=lane_id,
            azure_responses_deployment=azure_responses_deployment,
        )

    @staticmethod
    def prepare_headers_and_payload(
        context: ExecutionContext, payload: Dict[str, Any]
    ) -> Tuple[Dict[str, str], Dict[str, Any]]:
        """
        Prepare HTTP headers and potentially modify payload based on context.

        Args:
            context: Execution context with auth info
            payload: Original request payload

        Returns:
            Tuple of (headers, modified_payload)
        """
        # httpx must generate the multipart boundary for file-upload requests;
        # setting Content-Type manually would omit that required boundary.
        headers = {} if is_multipart_payload(payload) else {"Content-Type": "application/json"}
        if context.auth_header and context.auth_value:
            headers[context.auth_header] = context.auth_value

        # OpenWebUI requires model name injection
        if context.provider_type in {"logosnode"} or "openwebui" in context.provider_name.lower():
            payload = set_payload_field(payload, "model", context.model_name)

        # The Qwen3.8 chat template only accepts xhigh/medium/low as reasoning
        # effort, but clients such as Claude Code send the Anthropic value
        # "high" in every request. vLLM forwards the value to the template,
        # which rejects it with an error surfaced as HTTP 500 — map the wider
        # client scale onto the accepted one before forwarding (#749).
        payload = normalize_reasoning_effort(payload, context.model_name)

        # Azure Responses API resolves the deployment from the body's "model"
        # field (the URL carries no deployment segment). Clients address models
        # by the catalogued (served) name, which can differ from the Azure
        # deployment id — rewrite it so Azure can resolve the deployment.
        if context.azure_responses_deployment:
            payload = set_payload_field(payload, "model", context.azure_responses_deployment)

        return headers, payload

    # .../openai/deployments/<deployment-id>/responses[?query]
    _AZURE_RESPONSES_RE = re.compile(
        r"^(?P<host>https?://[^/]+)/openai/deployments/(?P<deployment>[^/?]+)/responses(?P<query>\?.*)?$"
    )

    # .../openai/deployments/<deployment-id>/<operation>[?query]
    _AZURE_DEPLOYMENT_OP_RE = re.compile(
        r"^(?P<prefix>https?://[^/]+/openai/deployments/[^/?]+)/(?P<operation>[^?]+?)/?(?:\?(?P<query>.*))?$"
    )

    # Operations a client may select via the inbound path. A deployment stores
    # exactly one endpoint (the sync classifies gpt-5.x to "responses",
    # everything chat-shaped to "chat/completions"), but most chat deployments
    # serve both APIs — so the client's chosen surface wins over the stored
    # default. Whisper deployments are stored as audio/transcriptions but also
    # serve audio/translations, so those two operations are swappable as well.
    _SWAPPABLE_AZURE_OPS = {"chat/completions", "responses"}
    _SWAPPABLE_AZURE_AUDIO_OPS = {"audio/transcriptions", "audio/translations"}

    @staticmethod
    def _requested_operation(request_path: Optional[str]) -> Optional[str]:
        """Extract the operation a client addressed via the inbound path.

        ``v1/responses`` -> ``responses``; ``/v1/chat/completions`` ->
        ``chat/completions``. Returns ``None`` for paths that are not one of
        the swappable operations.
        """
        if not request_path:
            return None
        path = request_path.strip("/")
        for prefix in ("v1/", "v2/"):
            if path.startswith(prefix):
                path = path[len(prefix) :]
                break
        swappable = ContextResolver._SWAPPABLE_AZURE_OPS | ContextResolver._SWAPPABLE_AZURE_AUDIO_OPS
        return path if path in swappable else None

    @staticmethod
    def _align_azure_operation(endpoint: str, request_path: Optional[str]) -> str:
        """Re-target a stored Azure deployment endpoint to the inbound operation.

        The per-model endpoint stores one default operation (e.g.
        ``.../deployments/gpt-4o/chat/completions?api-version=...``), but the
        client picks the API surface per request: ``/v1/responses`` must reach
        Azure's Responses API even when the deployment's stored default is
        chat/completions (and vice versa for gpt-5.x deployments stored with a
        ``responses`` endpoint). Swaps the operation suffix and pins the
        api-version configured for the target operation (the stored chat
        api-version may predate Responses-API availability). All other URLs
        (non-Azure, non-swappable operations) are returned unchanged.
        """
        requested = ContextResolver._requested_operation(request_path)
        if requested is None:
            return endpoint
        match = ContextResolver._AZURE_DEPLOYMENT_OP_RE.match(endpoint or "")
        if not match:
            return endpoint
        current = match.group("operation")
        same_family = (
            current in ContextResolver._SWAPPABLE_AZURE_OPS and requested in ContextResolver._SWAPPABLE_AZURE_OPS
        ) or (
            current in ContextResolver._SWAPPABLE_AZURE_AUDIO_OPS
            and requested in ContextResolver._SWAPPABLE_AZURE_AUDIO_OPS
        )
        if current == requested or not same_family:
            return endpoint
        params = dict(parse_qsl(match.group("query") or ""))
        api_version = AZURE_OPERATION_API_VERSIONS.get(requested)
        if api_version:
            params["api-version"] = api_version
        query = f"?{urlencode(params)}" if params else ""
        return f"{match.group('prefix')}/{requested}{query}"

    @staticmethod
    def _azure_responses_route(forward_url: str) -> Tuple[Optional[str], Optional[str]]:
        """Collapse a deployment-scoped Azure Responses URL to its real form.

        The auto-sync stores Responses deployments as
        ``.../openai/deployments/<id>/responses?api-version=...`` so the
        deployment id is recoverable (the scheduler reads it for capacity, and
        we need it here). Azure's actual route is ``.../openai/responses`` with
        no deployment segment — Azure resolves the deployment from the request
        body's ``model`` field.

        Returns ``(real_url, deployment_id)`` for such URLs so the caller can
        forward to the collapsed URL and rewrite the body ``model``; returns
        ``(None, None)`` for any other URL (e.g. chat/completions, which carry
        the deployment in the path and need no rewrite).
        """
        match = ContextResolver._AZURE_RESPONSES_RE.match(forward_url or "")
        if not match:
            return None, None
        host = match.group("host")
        deployment = match.group("deployment")
        query = match.group("query") or ""
        return f"{host}/openai/responses{query}", deployment

    @staticmethod
    def _merge_url(base_url: str, endpoint: str) -> str:
        """Merge base URL and endpoint path."""
        if endpoint.startswith("http"):
            return endpoint
        base = base_url.rstrip("/")
        path = endpoint.lstrip("/")
        return f"{base}/{path}"

    @staticmethod
    def _cloud_forward_url(
        base_url: str,
        request_path: Optional[str],
        endpoint_fallback: Optional[str],
    ) -> str:
        """Build forward URL for a cloud upstream provider.

        Prefer reusing the inbound `request_path` so we forward like-for-like
        (e.g. /v1/chat/completions in → /v1/chat/completions out). If the
        provider's base_url already ends in /v1 or /v2 and the inbound path
        starts with the same prefix, strip the prefix to avoid duplicating it
        (".../v1" + "v1/chat/completions" → ".../v1/chat/completions").

        Falls back to the per-model endpoint when no request_path is supplied
        (background jobs that don't know the original HTTP route).

        A fully-qualified per-model endpoint is authoritative and used almost
        as-is. Azure deployments encode the deployment name and ``api-version``
        in the URL (e.g. ``.../openai/deployments/gpt-41-mini/chat/completions?api-version=...``),
        none of which can be reconstructed from ``base_url`` + inbound path —
        doing so yields ``.../openai/deployments/v1/chat/completions``, which
        Azure rejects with 404. The only adjustment is the operation suffix:
        when the client addresses a different (swappable) API surface than the
        stored default — e.g. ``/v1/responses`` against a chat deployment —
        the suffix is re-targeted via ``_align_azure_operation``. The
        like-for-like ``request_path`` rewrite below only applies to
        OpenAI-shaped upstreams whose ``base_url`` is a plain ``/v1`` host and
        whose per-model endpoint is relative or empty.
        """
        if endpoint_fallback and endpoint_fallback.startswith("http"):
            return ContextResolver._align_azure_operation(endpoint_fallback, request_path)
        base = (base_url or "").rstrip("/")
        if not request_path:
            return ContextResolver._merge_url(base_url, endpoint_fallback or "")
        path = request_path.lstrip("/")
        for prefix in ("v1/", "v2/"):
            if base.endswith("/" + prefix.rstrip("/")) and path.startswith(prefix):
                path = path[len(prefix) :]
                break
        return f"{base}/{path}"
