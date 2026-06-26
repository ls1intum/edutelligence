"""Azure deployment auto-sync.

Discovers the deployments live on each Azure OpenAI resource and upserts them
into the Logos database (``models`` + ``model_provider``) so the catalogue
mirrors what is actually deployed. Runs once on startup and then every 24h.

Azure quirks this handles:
  * Deployments are listed via the *data-plane* endpoint
    ``GET /openai/deployments?api-version=2023-03-15-preview`` (newer
    api-versions 404 this route).
  * A deployment's ``id`` (the name in the URL path) can differ from the
    ``model`` it serves (e.g. id ``gpt-4o`` serving model ``gpt-5.1``). Models
    are named by the served ``model``; the URL uses the deployment ``id``.
  * Different model families need different operation paths / api-versions
    (chat completions, the Responses API, embeddings, audio, images).
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

import httpx

from logos.dbutils.dbmanager import DBManager

logger = logging.getLogger(__name__)

# Data-plane api-version that supports listing deployments with api-key auth.
DEPLOYMENTS_LIST_API_VERSION = os.getenv("LOGOS_AZURE_DEPLOYMENTS_API_VERSION", "2023-03-15-preview")

# Per-operation api-versions (env-overridable). Defaults mirror what the prod
# resource already uses for the gpt-4.1 (chat) and gpt-5.4 (responses) families.
_CHAT_API_VERSION = os.getenv("LOGOS_AZURE_CHAT_API_VERSION", "2025-01-01-preview")
_RESPONSES_API_VERSION = os.getenv("LOGOS_AZURE_RESPONSES_API_VERSION", "2025-04-01-preview")
_EMBEDDINGS_API_VERSION = os.getenv("LOGOS_AZURE_EMBEDDINGS_API_VERSION", "2024-02-01")
_AUDIO_API_VERSION = os.getenv("LOGOS_AZURE_AUDIO_API_VERSION", "2024-06-01")
_IMAGE_API_VERSION = os.getenv("LOGOS_AZURE_IMAGE_API_VERSION", "2024-02-01")

SYNC_INTERVAL_S = int(os.getenv("LOGOS_AZURE_SYNC_INTERVAL_S", str(24 * 60 * 60)))
SYNC_ENABLED = os.getenv("LOGOS_AZURE_SYNC_ENABLED", "true").lower() == "true"


@dataclass(frozen=True)
class AzureOperation:
    """How to address a model family on Azure."""

    # Operation suffix appended after the deployment segment, e.g.
    # "chat/completions". Empty for the Responses API, which is addressed at
    # /openai/responses (no deployment in the path; model goes in the body).
    suffix: str
    api_version: str
    uses_deployment_path: bool = True


def classify_azure_operation(model_name: str) -> AzureOperation:
    """Map a served Azure model name to its operation path + api-version.

    Best-effort by family. Chat completions is the default; the special cases
    cover embeddings, audio (whisper/tts), images, and the Responses API used
    by the gpt-5.x reasoning models (gpt-5-chat stays on chat/completions).
    """
    m = model_name.lower()

    if "embedding" in m or m.startswith("te-"):
        return AzureOperation("embeddings", _EMBEDDINGS_API_VERSION)
    if "whisper" in m or "transcribe" in m:
        return AzureOperation("audio/transcriptions", _AUDIO_API_VERSION)
    if "tts" in m or m.endswith("-tts"):
        return AzureOperation("audio/speech", _AUDIO_API_VERSION)
    if "dall-e" in m or m.startswith("dalle") or "image" in m:
        return AzureOperation("images/generations", _IMAGE_API_VERSION)
    # gpt-5.x reasoning models use the Responses API (matches existing DB
    # config for the gpt-5.4 family); gpt-5-chat is a normal chat model.
    if re.match(r"^gpt-5", m) and "chat" not in m:
        return AzureOperation("", _RESPONSES_API_VERSION, uses_deployment_path=False)
    return AzureOperation("chat/completions", _CHAT_API_VERSION)


def azure_host_from_base_url(base_url: str) -> str:
    """Extract the scheme://host root from a provider base_url.

    ``https://ase-se01.openai.azure.com/openai/deployments/`` -> ``https://ase-se01.openai.azure.com``
    """
    parts = urlsplit(base_url or "")
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"Cannot derive Azure host from base_url: {base_url!r}")
    return f"{parts.scheme}://{parts.netloc}"


def build_azure_endpoint(host: str, deployment_id: str, op: AzureOperation) -> str:
    """Build the fully-qualified Azure endpoint URL for a deployment."""
    host = host.rstrip("/")
    if not op.uses_deployment_path:
        return f"{host}/openai/responses?api-version={op.api_version}"
    return f"{host}/openai/deployments/{deployment_id}/{op.suffix}?api-version={op.api_version}"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def plan_sync(host: str, deployments: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Turn the raw Azure deployment list into desired DB rows.

    - Keeps only ``status == 'succeeded'`` deployments.
    - Names each model by the served ``model`` field.
    - When several deployments serve the same model, prefers the one whose
      deployment id matches the model name; otherwise the first by id.
    - Builds the per-model endpoint URL.

    Returns a list of ``{"model_name", "endpoint"}`` (one per served model).
    """
    by_model: Dict[str, List[Dict[str, Any]]] = {}
    for dep in deployments:
        if (dep.get("status") or "").lower() not in ("", "succeeded"):
            continue
        served = dep.get("model")
        dep_id = dep.get("id")
        if not served or not dep_id:
            continue
        by_model.setdefault(served, []).append(dep)

    planned: List[Dict[str, str]] = []
    for model_name, deps in sorted(by_model.items()):
        deps_sorted = sorted(deps, key=lambda d: d["id"])
        chosen = next(
            (d for d in deps_sorted if _norm(d["id"]) == _norm(model_name)),
            deps_sorted[0],
        )
        op = classify_azure_operation(model_name)
        # The Responses API addresses the deployment via the request body's
        # "model" field, and Logos forwards the client's body verbatim for
        # cloud providers (no model rewrite). So a Responses model is only
        # routable when its deployment id matches the served model name —
        # otherwise the body would carry a name Azure can't resolve. Skip
        # those rather than create a broken entry.
        if not op.uses_deployment_path and _norm(chosen["id"]) != _norm(model_name):
            logger.warning(
                "Azure deployment sync: skipping Responses-API model %r — served by deployment "
                "%r whose name differs, so it can't be addressed via the request body",
                model_name,
                chosen["id"],
            )
            continue
        planned.append(
            {
                "model_name": model_name,
                "endpoint": build_azure_endpoint(host, chosen["id"], op),
            }
        )
    return planned


async def fetch_azure_deployments(host: str, api_key: str, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Fetch the raw deployment list from an Azure resource (data-plane)."""
    url = f"{host.rstrip('/')}/openai/deployments?api-version={DEPLOYMENTS_LIST_API_VERSION}"
    resp = await client.get(url, headers={"api-key": api_key}, timeout=30.0)
    resp.raise_for_status()
    return resp.json().get("data", [])


class AzureDeploymentSyncService:
    """Periodically syncs Azure deployments into the DB (startup + every 24h)."""

    def __init__(
        self,
        interval_s: int = SYNC_INTERVAL_S,
        enabled: bool = SYNC_ENABLED,
        on_models_changed: Optional[Callable[[bool], "asyncio.Future | Any"]] = None,
    ):
        self._interval_s = interval_s
        self._enabled = enabled
        self._on_models_changed = on_models_changed
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if not self._enabled:
            logger.info("Azure deployment sync disabled (LOGOS_AZURE_SYNC_ENABLED=false)")
            return
        # Initial sync runs inline so the catalogue is fresh before the first
        # request; failures are logged but never block startup.
        await self.run_once()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval_s)
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("Azure deployment sync cycle failed")

    async def run_once(self) -> None:
        """Sync every Azure provider once. Never raises."""
        try:
            with DBManager() as db:
                providers = db.get_azure_providers()
        except Exception:  # noqa: BLE001
            logger.exception("Azure deployment sync: failed to list providers")
            return

        if not providers:
            logger.debug("Azure deployment sync: no Azure providers configured")
            return

        any_new = False
        async with httpx.AsyncClient() as client:
            for provider in providers:
                changed = await self._sync_provider(provider, client)
                any_new = any_new or changed

        if any_new and self._on_models_changed is not None:
            try:
                await self._on_models_changed(True)
            except Exception:  # noqa: BLE001
                logger.exception("Azure deployment sync: runtime refresh failed")

    async def _sync_provider(self, provider: Dict[str, Any], client: httpx.AsyncClient) -> bool:
        pid = provider["id"]
        name = provider.get("name", f"provider-{pid}")
        api_key = provider.get("api_key")
        if not api_key:
            logger.warning("Azure deployment sync: provider %s (%s) has no api_key; skipping", pid, name)
            return False
        try:
            host = azure_host_from_base_url(provider.get("base_url", ""))
            raw = await fetch_azure_deployments(host, api_key, client)
        except Exception:  # noqa: BLE001
            logger.exception("Azure deployment sync: fetch failed for provider %s (%s)", pid, name)
            return False

        planned = plan_sync(host, raw)
        try:
            with DBManager() as db:
                newly = db.sync_azure_deployments(pid, planned)
        except Exception:  # noqa: BLE001
            logger.exception("Azure deployment sync: DB upsert failed for provider %s (%s)", pid, name)
            return False

        logger.info(
            "Azure deployment sync: provider %s (%s) — %d deployment(s) → %d model(s), %d new%s",
            pid,
            name,
            len(raw),
            len(planned),
            len(newly),
            f" ({', '.join(newly)})" if newly else "",
        )
        return bool(newly)
