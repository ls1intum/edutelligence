"""Operator-facing view of the stack.

Everything here goes through the same HTTP endpoints the UI and the node
tooling use, so a test asserting on node state is asserting on what an operator
would actually see — not on orchestrator internals reachable only in-process.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class NodeView:
    """One worker node as the orchestrator sees it.

    ``status`` is the raw ``/logosdb/providers/logosnode/status`` payload. The
    accessors below unwrap it, because the interesting values sit two levels
    down: ``runtime.devices`` is a *device summary* (telemetry flags, totals)
    whose own ``devices`` key holds the per-card list.
    """

    provider_id: int
    name: str
    status: dict[str, Any]

    @property
    def runtime(self) -> dict[str, Any]:
        return self.status.get("runtime") or {}

    @property
    def device_summary(self) -> dict[str, Any]:
        return self.runtime.get("devices") or {}

    @property
    def devices(self) -> list[dict[str, Any]]:
        return self.device_summary.get("devices") or []

    @property
    def lanes(self) -> list[dict[str, Any]]:
        return self.runtime.get("lanes") or []

    @property
    def total_vram_mb(self) -> float:
        return sum(float(d.get("memory_total_mb") or 0) for d in self.devices)

    @property
    def free_vram_mb(self) -> float:
        return float(self.device_summary.get("free_memory_mb") or 0)

    @property
    def gpu_names(self) -> list[str]:
        return [str(d.get("name") or "") for d in self.devices]

    @property
    def telemetry_available(self) -> bool:
        return bool(self.device_summary.get("telemetry_available"))

    @property
    def degraded_reason(self) -> str:
        return str(self.device_summary.get("degraded_reason") or "")

    @property
    def node_health(self) -> dict[str, Any]:
        return self.runtime.get("node_health") or {}


class AdminClient:
    """Thin wrapper over the root-only logosnode endpoints."""

    def __init__(
        self,
        base_url: str,
        admin_key: str,
        timeout: float = 30.0,
        internal_secret: str = "logos-e2e-internal-secret",
    ) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        self._admin_key = admin_key
        self._internal_secret = internal_secret

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AdminClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- reads ------------------------------------------------------------

    def scheduler_state(self) -> dict[str, Any]:
        response = self._client.get(
            "/logosdb/scheduler_state",
            headers={"Authorization": f"Bearer {self._admin_key}"},
        )
        response.raise_for_status()
        return response.json()

    def provider_status(self) -> list[dict[str, Any]]:
        """Connection state of every local provider.

        This is the orchestrator's own liveness view — the worker registry,
        which is the only place a live WebSocket session is visible.
        """
        response = self._client.get(
            "/internal/provider_status",
            headers={"Authorization": f"Bearer {self._internal_secret}"},
        )
        response.raise_for_status()
        return response.json().get("providers") or []

    def connected_nodes(self) -> list[NodeView]:
        """Worker nodes whose WebSocket session is live.

        Liveness comes from the worker registry rather than from
        ``scheduler_state``: the scheduler's SDI facade only lists a provider
        once it has *deployments* attached, so a freshly registered node with no
        models yet is fully connected and still absent there. Reading the facade
        would report an idle fleet as an offline one.

        An empty list while containers are running is normal during startup —
        registration is an HTTP call, but the node is only usable once its
        session is established.
        """
        try:
            providers = self.provider_status()
        except httpx.HTTPError:
            return []

        nodes = []
        for provider in providers:
            if not provider.get("connected"):
                continue
            provider_id = int(provider["provider_id"])
            try:
                status = self.node_status(provider_id)
            except httpx.HTTPError:
                # The session dropped between the two calls; not connected.
                continue
            nodes.append(
                NodeView(
                    provider_id=provider_id,
                    name=str(provider.get("name") or ""),
                    status=status or {},
                )
            )
        return nodes

    def node_status(self, provider_id: int) -> dict[str, Any]:
        response = self._client.post(
            "/logosdb/providers/logosnode/status",
            json={"logos_key": self._admin_key, "provider_id": provider_id},
        )
        response.raise_for_status()
        return response.json()

    def node_device_summary(self, provider_id: int) -> dict[str, Any]:
        """The node's device summary: telemetry flags, totals, and the card list.

        The endpoint wraps a ``DeviceSummary`` under a ``devices`` key, and that
        summary has its own ``devices`` list inside it — hence the two accessors
        rather than one.
        """
        response = self._client.post(
            "/logosdb/providers/logosnode/devices",
            json={"logos_key": self._admin_key, "provider_id": provider_id},
        )
        response.raise_for_status()
        return response.json().get("devices") or {}

    def node_devices(self, provider_id: int) -> list[dict[str, Any]]:
        """The per-card list this node reports."""
        return self.node_device_summary(provider_id).get("devices") or []

    def node_lanes(self, provider_id: int) -> list[dict[str, Any]]:
        response = self._client.post(
            "/logosdb/providers/logosnode/lanes",
            json={"logos_key": self._admin_key, "provider_id": provider_id},
        )
        response.raise_for_status()
        return response.json().get("lanes") or []

    # -- writes -----------------------------------------------------------

    def register_node(
        self,
        provider_name: str,
        base_url: str = "",
        privacy_level: str = "LOCAL",
    ) -> dict[str, Any]:
        """Register a worker node. The privacy level is required by the endpoint.

        Defaulted here for test convenience only — the API itself has no default,
        so that a rented or third-party worker cannot be registered as
        operator-controlled hardware by omission.
        """
        response = self._client.post(
            "/logosdb/providers/logosnode/register",
            json={
                "logos_key": self._admin_key,
                "provider_name": provider_name,
                "base_url": base_url,
                "privacy_level": privacy_level,
            },
        )
        response.raise_for_status()
        return response.json()

    def raw_post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        """Unchecked POST, for tests asserting on rejection status codes."""
        return self._client.post(path, json=payload)
