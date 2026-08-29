"""
Temporary (volatile) provider registry.

A temporary provider is an OpenAI-compatible host — e.g. LM Studio on a laptop
reachable through a tunnel — that an operator wants to route through Logos for
a short period. It is registered at runtime with only a base URL and an auth
key, automatically discovers its models via ``GET /v1/models``, and lives
purely in orchestrator memory: nothing about it is ever written to the
database, so a restart of the orchestrator makes it disappear, which is
exactly the volatility the feature is about.

A background health loop probes every registered provider. As soon as its
probes fail (by default: the first one) the provider is marked ``unhealthy``
and its models stop being routed — requests fail fast with a clear error
instead of hanging on a dead host. Once the host is gone for longer than the
expiry window the entry is removed on its own. When the host comes back, the
provider becomes healthy again and routing resumes — no re-registration
needed.

Access: a temporary provider is owned by the API key it was registered for
(the "add to user" privacy aspect of issue #421). Only that key and
``logos_admin`` keys may list or route to its models.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

STATUS_HEALTHY = "healthy"
STATUS_UNHEALTHY = "unhealthy"


class TempProviderError(Exception):
    """Raised when a temporary provider cannot be reached or is malformed."""


def normalize_base_url(base_url: str) -> str:
    """Normalise an OpenAI-compatible base URL to a ``.../v1`` form.

    ``http://host:1234`` becomes ``http://host:1234/v1`` (LM Studio, Ollama
    and friends expose their OpenAI surface under ``/v1``); a URL that already
    ends in ``/v1`` or ``/v2`` is kept as-is, only trailing slashes are
    dropped. Raises :class:`TempProviderError` for non-http(s) URLs so the
    registry never points at a non-absolute or local-file target.
    """
    url = (base_url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TempProviderError(f"base_url must be an absolute http(s) URL, got: {base_url!r}")
    last_segment = parsed.path.rstrip("/").rsplit("/", 1)[-1].lower()
    if last_segment not in {"v1", "v2"}:
        url = f"{url}/v1"
    return url


def _planner_alias(model_name: str) -> str:
    """Same alias form main.py's model resolution uses (``/``, ``:``, space → ``_``)."""
    return str(model_name or "").strip().replace("/", "_").replace(":", "_").replace(" ", "_")


def match_model_name(requested: str, available: List[str]) -> Optional[str]:
    """Resolve a requested name against discovered model names.

    Accepts the exact name or — like ``main._resolve_requested_model_name`` —
    the planner-safe alias with underscores, returning the canonical name on
    an unambiguous match and ``None`` otherwise.
    """
    requested = str(requested or "").strip()
    if not requested:
        return None
    for name in available:
        if name == requested:
            return name
    alias_matches = {
        name for name in available if requested in {_planner_alias(name), f"planner-{_planner_alias(name)}"}
    }
    if len(alias_matches) == 1:
        return next(iter(alias_matches))
    return None


@dataclass
class TempProvider:
    """One volatile, in-memory provider registration."""

    provider_id: str
    name: str
    base_url: str
    api_key: str
    owner_api_key_id: int
    registered_at: float  # wall-clock epoch, for display
    models: List[str] = field(default_factory=list)
    status: str = STATUS_HEALTHY
    consecutive_failures: int = 0
    last_success_at: Optional[float] = None  # wall-clock epoch, for display
    failures_started_mono: Optional[float] = None  # monotonic anchor for the expiry window

    @property
    def is_healthy(self) -> bool:
        return self.status == STATUS_HEALTHY

    def to_public_dict(self) -> Dict[str, Any]:
        """JSON-safe view. The upstream API key is in-memory only and never exported."""
        return {
            "provider_id": self.provider_id,
            "name": self.name,
            "base_url": self.base_url,
            "status": self.status,
            "models": list(self.models),
            "owner_api_key_id": self.owner_api_key_id,
            "registered_at": self.registered_at,
            "last_success_at": self.last_success_at,
            "consecutive_failures": self.consecutive_failures,
        }


class TempProviderRegistry:
    """In-memory registry of temporary providers with a background health loop.

    The registry never touches the database. All state is lost when the
    orchestrator process stops, by design.
    """

    def __init__(
        self,
        health_interval_s: float = 30.0,
        unhealthy_after: int = 1,
        expiry_s: float = 86400.0,
        probe_timeout_s: float = 10.0,
        probe: Optional[Callable[[str, str], List[str]]] = None,
    ):
        """
        Args:
            health_interval_s: Seconds between health/model-discovery probes.
            unhealthy_after: Consecutive failed probes before a provider is
                marked unhealthy (and its models stop being routed). The
                default of 1 fails fast: a probe that just succeeded a moment
                ago rarely fails because of a transient glitch, and a dead
                host must stop receiving requests quickly. Raise it for hosts
                behind a flaky tunnel.
            expiry_s: How long an unhealthy provider may stay unreachable
                before it is removed from the registry entirely.
            probe_timeout_s: Per-probe HTTP timeout in seconds.
            probe: Optional async override ``probe(base_url, api_key) -> model
                names`` — the unit tests use this instead of real HTTP.
        """
        self._providers: Dict[str, TempProvider] = {}
        self._interval_s = float(health_interval_s)
        self._unhealthy_after = max(1, int(unhealthy_after))
        self._expiry_s = float(expiry_s)
        self._probe_timeout_s = float(probe_timeout_s)
        self._probe = probe
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def add_provider(
        self,
        base_url: str,
        api_key: str,
        owner_api_key_id: int,
        name: Optional[str] = None,
    ) -> TempProvider:
        """Register a temporary provider and immediately discover its models.

        Raises:
            TempProviderError: If the URL is malformed, a provider for the
                same URL already exists, or the initial ``/models`` probe
                fails (bad URL, bad key, host already offline).
        """
        normalized = normalize_base_url(base_url)
        for existing in self._providers.values():
            if existing.base_url == normalized:
                raise TempProviderError(f"A temporary provider for {normalized} is already registered")

        if name:
            provider_name = name.strip()
        else:
            provider_name = urlparse(normalized).netloc

        try:
            models = await self._fetch_models(normalized, api_key)
        except TempProviderError as exc:
            raise TempProviderError(f"Initial model discovery failed: {exc}") from exc
        if not models:
            raise TempProviderError(f"No models discovered at {normalized}/models")

        entry = TempProvider(
            provider_id=f"tmp-{uuid.uuid4().hex[:8]}",
            name=provider_name,
            base_url=normalized,
            api_key=api_key or "",
            owner_api_key_id=int(owner_api_key_id),
            registered_at=time.time(),
            models=models,
            status=STATUS_HEALTHY,
            last_success_at=time.time(),
        )
        self._providers[entry.provider_id] = entry
        logger.info(
            "Registered temporary provider '%s' (%s) with %d model(s) for api_key_id=%s",
            provider_name,
            normalized,
            len(models),
            owner_api_key_id,
        )
        return entry

    def remove_provider(self, provider_id: str) -> bool:
        """Remove a provider by id. Returns True if it existed."""
        removed = self._providers.pop(provider_id, None)
        if removed is not None:
            logger.info("Removed temporary provider '%s' (%s)", removed.name, removed.base_url)
        return removed is not None

    def get(self, provider_id: str) -> Optional[TempProvider]:
        return self._providers.get(provider_id)

    def __len__(self) -> int:
        return len(self._providers)

    # ------------------------------------------------------------------
    # Lookup / access control
    # ------------------------------------------------------------------

    def find_by_model(self, requested: str) -> Optional[tuple[TempProvider, str]]:
        """(provider, canonical model name) if any registered provider serves the name."""
        for entry in self._providers.values():
            matched = match_model_name(requested, entry.models)
            if matched is not None:
                return entry, matched
        return None

    def list_for_api_key(self, api_key_id: int, is_admin: bool = False) -> List[TempProvider]:
        """Providers visible to a key: its own, plus everything for admins."""
        visible = [entry for entry in self._providers.values() if is_admin or entry.owner_api_key_id == api_key_id]
        return sorted(visible, key=lambda entry: entry.registered_at)

    def can_access(self, entry: TempProvider, api_key_id: int, is_admin: bool) -> bool:
        return is_admin or entry.owner_api_key_id == api_key_id

    # ------------------------------------------------------------------
    # Health loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background health loop (no-op if already running)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._health_loop())

    async def stop(self) -> None:
        """Cancel the background health loop and wait for it to finish."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval_s)
            for entry in list(self._providers.values()):
                try:
                    await self._probe_entry(entry)
                except Exception:  # noqa: BLE001 — one broken probe must not kill the loop
                    logger.exception("Temporary provider health probe crashed for %s", entry.name)

    async def _probe_entry(self, entry: TempProvider) -> None:
        """Probe one provider: refresh its model list or record the failure."""
        now_mono = time.monotonic()
        try:
            models = await self._fetch_models(entry.base_url, entry.api_key)
        except Exception as exc:  # noqa: BLE001 — any probe error counts as unreachable
            entry.consecutive_failures += 1
            newly_unhealthy = entry.status == STATUS_HEALTHY and entry.consecutive_failures >= self._unhealthy_after
            if newly_unhealthy:
                entry.status = STATUS_UNHEALTHY
                entry.failures_started_mono = now_mono
            logger.warning(
                "Temporary provider '%s' (%s) probe failed (%d consecutive%s): %s",
                entry.name,
                entry.base_url,
                entry.consecutive_failures,
                " — marked unhealthy" if newly_unhealthy else "",
                exc,
            )
            if (
                entry.status == STATUS_UNHEALTHY
                and entry.failures_started_mono is not None
                and now_mono - entry.failures_started_mono >= self._expiry_s
            ):
                self.remove_provider(entry.provider_id)
                logger.warning(
                    "Temporary provider '%s' (%s) expired after %ds unreachable and was removed",
                    entry.name,
                    entry.base_url,
                    int(self._expiry_s),
                )
            return

        entry.consecutive_failures = 0
        entry.failures_started_mono = None
        entry.last_success_at = time.time()
        if set(models) != set(entry.models):
            logger.info("Temporary provider '%s' model list changed: %s -> %s", entry.name, entry.models, models)
            entry.models = models
        if entry.status == STATUS_UNHEALTHY:
            entry.status = STATUS_HEALTHY
            logger.info("Temporary provider '%s' (%s) is reachable again", entry.name, entry.base_url)

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    async def _fetch_models(self, base_url: str, api_key: str) -> List[str]:
        """GET ``{base_url}/models`` and return the list of model names.

        Raises:
            TempProviderError: On any transport error, non-2xx status, or a
                body that is not the OpenAI model-list shape.
        """
        if self._probe is not None:
            return await self._probe(base_url, api_key)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self._probe_timeout_s) as client:
                response = await client.get(f"{base_url}/models", headers=headers)
        except httpx.HTTPError as exc:
            raise TempProviderError(f"{type(exc).__name__}: {exc}") from exc

        if response.status_code >= 400:
            raise TempProviderError(f"model discovery failed with HTTP {response.status_code}")
        try:
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
        except (ValueError, AttributeError):
            raise TempProviderError("model discovery returned a non-JSON body") from None
        if not isinstance(data, list):
            raise TempProviderError("model discovery body is not an OpenAI model list")

        names: List[str] = []
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
                names.append(item["id"].strip())
        return names
