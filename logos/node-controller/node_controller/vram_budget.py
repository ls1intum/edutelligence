"""
VRAM budget manager — tracks and estimates GPU memory usage across lanes.

Uses GpuMetricsCollector data (nvidia-smi) and per-lane /api/ps queries
to provide VRAM estimation, budget validation, and utilisation reporting.
"""

from __future__ import annotations

import logging

from node_controller.gpu import GpuMetricsCollector
from node_controller.models import GpuSnapshot, LaneConfig

logger = logging.getLogger("node_controller.vram_budget")

# Rough per-slot KV cache overhead factors (bytes per context token per layer per head_dim * 2).
# These are approximations; actual sizes depend on model architecture.
_KV_BYTES_PER_TOKEN_Q8 = 1.0   # q8_0 quantised KV
_KV_BYTES_PER_TOKEN_F16 = 2.0  # full f16 KV


class VramBudgetManager:
    """Estimates and tracks VRAM usage for lane configurations."""

    def __init__(self, gpu_collector: GpuMetricsCollector) -> None:
        self._gpu = gpu_collector

    async def get_snapshot(self) -> GpuSnapshot:
        return await self._gpu.get_snapshot()

    async def free_vram_mb(self) -> float:
        snap = await self._gpu.get_snapshot()
        return snap.free_vram_mb

    async def total_vram_mb(self) -> float:
        snap = await self._gpu.get_snapshot()
        return snap.total_vram_mb

    def estimate_lane_vram_mb(
        self,
        base_model_vram_mb: float,
        num_parallel: int,
        context_length: int,
        kv_cache_type: str = "q8_0",
        num_layers: int = 32,
        head_dim: int = 128,
        num_kv_heads: int = 8,
    ) -> float:
        """
        Estimate total VRAM for a lane including KV-cache overhead.

        KV cache per slot ≈ 2 * num_layers * num_kv_heads * head_dim * context_length * precision_bytes
        Total KV cache ≈ above * num_parallel

        This is an approximation — Ollama may allocate slightly differently.
        """
        if kv_cache_type == "q8_0":
            precision = _KV_BYTES_PER_TOKEN_Q8
        else:
            precision = _KV_BYTES_PER_TOKEN_F16

        kv_per_slot_bytes = (
            2  # K + V
            * num_layers
            * num_kv_heads
            * head_dim
            * context_length
            * precision
        )
        kv_total_bytes = kv_per_slot_bytes * num_parallel
        kv_total_mb = kv_total_bytes / (1024 * 1024)

        return base_model_vram_mb + kv_total_mb

    async def validate_lane_fits(
        self,
        lane_config: LaneConfig,
        base_model_vram_mb: float,
        reserved_mb: float = 0.0,
    ) -> tuple[bool, float, float]:
        """
        Check if a lane configuration would fit in available VRAM.

        Returns:
            (fits, estimated_mb, free_mb)
        """
        estimated = self.estimate_lane_vram_mb(
            base_model_vram_mb=base_model_vram_mb,
            num_parallel=lane_config.num_parallel,
            context_length=lane_config.context_length,
            kv_cache_type=lane_config.kv_cache_type,
        )
        free = await self.free_vram_mb() - reserved_mb
        return estimated <= free, estimated, free
