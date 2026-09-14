"""Fetch and merge every running lane's native vLLM ``/metrics`` into one export.

vLLM's own ``/metrics`` only binds to 127.0.0.1 on a per-lane, dynamically
allocated port — reachable from this worker process, never from Prometheus or
the orchestrator directly. This module fetches each running lane's raw
metrics text locally and merges them (relabeled by lane_id/model) into one
exposition-format blob, which the bridge then pushes to the orchestrator so
it can fold it into its own single ``/metrics`` scrape target.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from prometheus_client import CollectorRegistry, generate_latest

from logos_worker_node.vllm_metrics_merge import merge_metric_families

logger = logging.getLogger("logos_worker_node.vllm_metrics_export")

_FETCH_TIMEOUT_S = 3.0


class _StaticCollector:
    """Replays an already-computed list of metric families verbatim."""

    def __init__(self, families):
        self._families = families

    def collect(self):
        return iter(self._families)


async def _fetch_lane_metrics_text(client: httpx.AsyncClient, port: int) -> str | None:
    try:
        resp = await client.get(f"http://127.0.0.1:{port}/metrics", timeout=_FETCH_TIMEOUT_S)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    return resp.text


async def collect_vllm_metrics_text(endpoints: list[tuple[str, str, int]]) -> str:
    """Fetch and merge vLLM's raw ``/metrics`` from every (lane_id, model, port).

    Lanes are queried concurrently. A lane whose vLLM process doesn't answer
    in time is skipped — one stuck lane must not blank the export for every
    other lane on this worker.
    """
    if not endpoints:
        return ""
    async with httpx.AsyncClient() as client:
        texts = await asyncio.gather(*(_fetch_lane_metrics_text(client, port) for _, _, port in endpoints))

    sources = [
        ({"lane_id": lane_id, "model": model}, text)
        for (lane_id, model, _port), text in zip(endpoints, texts)
        if text
    ]
    families = merge_metric_families(sources)
    if not families:
        return ""
    registry = CollectorRegistry()
    registry.register(_StaticCollector(families))
    return generate_latest(registry).decode("utf-8")
