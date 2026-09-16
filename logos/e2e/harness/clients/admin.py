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
    provider_id: int
    name: str
    runtime: dict[str, Any]

    @property
    def devices(self) -> list[dict[str, Any]]:
        return self.runtime.get("devices") or []

    @property
    def lanes(self) -> list[dict[str, Any]]:
        return self.runtime.get("lanes") or []

    @property
    def total_vram_mb(self) -> float:
        return sum(float(d.get("memory_total_mb") or 0) for d in self.devices)

    @property
    def gpu_names(self) -> list[str]:
        return [str(d.get("name") or "") for d in self.devices]


class AdminClient:
    """Thin wrapper over the root-only logosnode endpoints."""

    def __init__(self, base_url: str, admin_key: str, timeout: float = 30.0) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        self._admin_key = admin_key

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

    def connected_nodes(self) -> list[NodeView]:
        """Worker nodes whose session is live, as the scheduler sees them.

        An empty list while containers are running is the normal state during
        startup — registration is HTTP, but a node only becomes usable once its
        WebSocket session is established.
        """
        try:
            state = self.scheduler_state()
        except httpx.HTTPError:
            return []
        providers = (state.get("logosnode") or {}).get("providers") or {}
        nodes = []
        for provider_id, payload in providers.items():
            nodes.append(
                NodeView(
                    provider_id=int(provider_id),
                    name=str(payload.get("name") or ""),
                    runtime=payload.get("runtime") or {},
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

    def node_devices(self, provider_id: int) -> list[dict[str, Any]]:
        response = self._client.post(
            "/logosdb/providers/logosnode/devices",
            json={"logos_key": self._admin_key, "provider_id": provider_id},
        )
        response.raise_for_status()
        return response.json().get("devices") or []

    def node_lanes(self, provider_id: int) -> list[dict[str, Any]]:
        response = self._client.post(
            "/logosdb/providers/logosnode/lanes",
            json={"logos_key": self._admin_key, "provider_id": provider_id},
        )
        response.raise_for_status()
        return response.json().get("lanes") or []

    # -- writes -----------------------------------------------------------

    def register_node(self, provider_name: str, base_url: str = "") -> dict[str, Any]:
        response = self._client.post(
            "/logosdb/providers/logosnode/register",
            json={"logos_key": self._admin_key, "provider_name": provider_name, "base_url": base_url},
        )
        response.raise_for_status()
        return response.json()

    def raw_post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        """Unchecked POST, for tests asserting on rejection status codes."""
        return self._client.post(path, json=payload)
