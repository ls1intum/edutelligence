"""Cloud model auto-sync.

Discovers the models each non-Azure cloud provider serves and mirrors them into
the Logos database (``models`` + ``model_provider``), the way
``azure_deployment_sync`` does for Azure resources. Runs once on startup and
then on an interval.

Two things this fixes, both reported against a Logos instance configured with
another Logos instance upstream:

  * The catalogue had to be maintained by hand. Azure resources self-scraped;
    every other cloud provider — including a Logos upstream — did not, so a
    model added upstream stayed invisible downstream until an operator typed
    its name in.
  * The context window was lost. ``GET /v1/models`` derives its window from the
    live workernode snapshots, which say nothing about a cloud provider, so a
    model reachable only through one was published with no window at all and
    clients that size their session from it fell back to a guess. What the
    upstream reports is now stored per provider (``cloud_model_context``) and
    republished.

Azure is deliberately excluded: its deployments are discovered through a
control-plane call that also yields the deployment id and api-version its
endpoint URL needs, none of which ``/v1/models`` reports.
"""

import asyncio
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from logos.dbutils.dbmanager import DBManager
from logos.dbutils.types import cloud_auth_header

logger = logging.getLogger(__name__)

SYNC_INTERVAL_S = int(os.getenv("LOGOS_CLOUD_MODEL_SYNC_INTERVAL_S", str(15 * 60)))
SYNC_ENABLED = os.getenv("LOGOS_CLOUD_MODEL_SYNC_ENABLED", "true").lower() == "true"
REQUEST_TIMEOUT_S = float(os.getenv("LOGOS_CLOUD_MODEL_SYNC_TIMEOUT_S", "30"))

# Context-window fields, in the order they are consulted. The first three are
# what a Logos upstream publishes (see ``_model_context_fields`` in main.py);
# the rest are what other OpenAI-shaped upstreams call the same number, so a
# vLLM or gateway upstream contributes a window too.
_CURRENT_MIN_KEYS = (
    "max_model_len_current_min",
    "max_model_len",
    "context_window",
    "context_length",
    "max_context_length",
)
_CURRENT_MAX_KEYS = ("max_model_len_current_max",)
_OVERALL_KEYS = ("max_model_len_overall",)

# What a Logos instance stamps on every model it serves. A listing where every
# entry carries it can only have come from another Logos.
_LOGOS_OWNER = "logos"


def models_url(base_url: str) -> str:
    """The ``/v1/models`` URL for a provider's base URL.

    A base URL that already ends in an API version keeps it — appending a
    second ``/v1`` is a 404 on every upstream that has the first one.
    """
    base = (base_url or "").rstrip("/")
    if not base:
        raise ValueError("Cloud provider has no base_url")
    tail = urlsplit(base).path.rstrip("/").rsplit("/", 1)[-1]
    return f"{base}/models" if tail in ("v1", "v2") else f"{base}/v1/models"


def _first_positive(entry: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[int]:
    for key in keys:
        try:
            value = int(entry[key])
        except (KeyError, TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def parse_model_list(body: Any) -> Tuple[List[str], Dict[str, Dict[str, int]], bool]:
    """Read an OpenAI-shaped model listing.

    Returns ``(model_names, context_by_model, looks_like_logos)``. Entries
    without an ``id`` are skipped; entries that report no window contribute a
    name but no context, so the model is still catalogued.

    ``looks_like_logos`` is True when the listing is non-empty and every entry
    is owned by "logos" — the marker that identifies another Logos instance.
    """
    data = body.get("data") if isinstance(body, dict) else body
    if not isinstance(data, list):
        return [], {}, False

    names: List[str] = []
    contexts: Dict[str, Dict[str, int]] = {}
    owners: List[str] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("id") or "").strip()
        if not name:
            continue
        names.append(name)
        owners.append(str(entry.get("owned_by") or "").strip().lower())

        current_min = _first_positive(entry, _CURRENT_MIN_KEYS)
        current_max = _first_positive(entry, _CURRENT_MAX_KEYS) or current_min
        overall = _first_positive(entry, _OVERALL_KEYS) or current_max
        window = {
            key: value
            for key, value in (
                ("current_min", current_min),
                ("current_max", current_max),
                ("overall", overall),
            )
            if value
        }
        if window:
            contexts[name] = window

    looks_like_logos = bool(owners) and all(owner == _LOGOS_OWNER for owner in owners)
    return names, contexts, looks_like_logos


async def fetch_models(url: str, headers: Dict[str, str], client: httpx.AsyncClient) -> Any:
    """Fetch a provider's model listing."""
    resp = await client.get(url, headers=headers, timeout=REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()


class CloudModelSyncService:
    """Periodically mirrors every non-Azure cloud provider's model list."""

    def __init__(
        self,
        interval_s: int = SYNC_INTERVAL_S,
        enabled: bool = SYNC_ENABLED,
        on_models_changed: Optional[Callable[..., "asyncio.Future | Any"]] = None,
    ):
        self._interval_s = interval_s
        self._enabled = enabled
        self._on_models_changed = on_models_changed
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if not self._enabled:
            logger.info("Cloud model sync disabled (LOGOS_CLOUD_MODEL_SYNC_ENABLED=false)")
            return
        # Initial sync runs inline so the catalogue and its context windows are
        # fresh before the first request; failures are logged, never fatal.
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
                logger.exception("Cloud model sync cycle failed")

    async def run_once(self) -> None:
        """Sync every eligible cloud provider once. Never raises."""
        try:
            with DBManager() as db:
                providers = db.get_cloud_sync_providers()
        except Exception:  # noqa: BLE001
            logger.exception("Cloud model sync: failed to list providers")
            return

        if not providers:
            logger.debug("Cloud model sync: no eligible cloud providers configured")
            return

        # Only a changed model set warrants a runtime refresh; a context window
        # that moved is read straight from the DB by /v1/models and needs none.
        any_models_changed = False
        any_new_models = False
        async with httpx.AsyncClient() as client:
            for provider in providers:
                changed, new_models = await self._sync_provider(provider, client)
                any_models_changed = any_models_changed or changed
                any_new_models = any_new_models or new_models

        if any_models_changed and self._on_models_changed is not None:
            try:
                await self._on_models_changed(rebuild_classifier=any_new_models)
            except Exception:  # noqa: BLE001
                logger.exception("Cloud model sync: runtime refresh failed")

    async def _sync_provider(self, provider: Dict[str, Any], client: httpx.AsyncClient) -> Tuple[bool, bool]:
        """Sync one provider. Returns ``(model_links_changed, new_model_rows)``."""
        pid = provider["id"]
        name = provider.get("name", f"provider-{pid}")
        try:
            url = models_url(provider.get("base_url", ""))
        except ValueError as exc:
            logger.warning("Cloud model sync: provider %s (%s) skipped: %s", pid, name, exc)
            return False, False

        headers = {"Accept": "application/json"}
        auth = cloud_auth_header(provider.get("auth_name"), provider.get("auth_format"), provider.get("api_key"))
        if auth is not None:
            headers[auth[0]] = auth[1]

        try:
            body = await fetch_models(url, headers, client)
        except Exception:  # noqa: BLE001
            # An upstream that is down, unreachable or does not serve a model
            # list at all must not disturb the catalogue: leaving the existing
            # links in place keeps its models routable until it answers again.
            logger.warning("Cloud model sync: model list unavailable for provider %s (%s) at %s", pid, name, url)
            logger.debug("Cloud model sync: fetch failed for provider %s (%s)", pid, name, exc_info=True)
            return False, False

        model_names, contexts, looks_like_logos = parse_model_list(body)
        if not model_names:
            logger.info("Cloud model sync: provider %s (%s) listed no models; leaving catalogue untouched", pid, name)
            return False, False

        try:
            with DBManager() as db:
                result = db.sync_cloud_models(pid, model_names)
                context_changed = db.replace_cloud_model_context(pid, contexts)
                self._note_logos_upstream(db, provider, looks_like_logos)
        except Exception:  # noqa: BLE001
            logger.exception("Cloud model sync: DB update failed for provider %s (%s)", pid, name)
            return False, False

        newly = result["new_models"]
        logger.info(
            "Cloud model sync: provider %s (%s) — %d model(s), %d new%s%s%s",
            pid,
            name,
            len(model_names),
            len(newly),
            f" ({', '.join(newly)})" if newly else "",
            f", {len(contexts)} with a context window" if contexts else ", none reporting a context window",
            "" if result["changed"] or context_changed else " [no DB change]",
        )
        return bool(result["changed"]), bool(newly)

    @staticmethod
    def _note_logos_upstream(db: DBManager, provider: Dict[str, Any], looks_like_logos: bool) -> None:
        """Record (or point out) that this upstream is another Logos instance.

        The type matters: a Logos upstream serves the Anthropic Messages API,
        so requests to it are forwarded verbatim instead of being translated
        into an OpenAI dialect. An unset type is filled in, because leaving it
        blank only loses fidelity; a type an operator already chose is never
        overwritten — the mismatch is logged so they can correct it.
        """
        if not looks_like_logos:
            return
        current = str(provider.get("cloud_provider_type") or "").lower()
        if current == "logos":
            return
        if current:
            logger.info(
                "Cloud model sync: provider %s (%s) answers like a Logos instance but is configured as '%s'. "
                "Set its cloud provider type to 'logos' so Anthropic Messages requests are passed through "
                "natively instead of translated.",
                provider["id"],
                provider.get("name"),
                current,
            )
            return
        db.set_cloud_provider_type(provider["id"], "logos")
        logger.info(
            "Cloud model sync: provider %s (%s) identified as a Logos upstream; cloud provider type set to 'logos'",
            provider["id"],
            provider.get("name"),
        )
