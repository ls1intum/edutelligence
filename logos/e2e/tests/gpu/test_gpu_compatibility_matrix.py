"""Compute capability drives the vLLM command line.

Every GPU-compatibility decision the worker makes is derived from
``nvidia-smi --query-gpu=compute_cap`` and materialises as an argument or an
environment variable on the spawn. Simulating the card is therefore enough to
test the decision — which is the entire reason this suite can run without GPUs.

The failure these pin down is real and expensive: FlashInfer's JIT crashes the
driver on pre-Ampere cards, so a lane on an sm75 node that does not get
``TRITON_ATTN`` takes the host with it.
"""

from __future__ import annotations

import pytest
from harness import lane as lane_harness
from harness.gpusim.scenario import GpuProfile, GpuScenario, VllmScript

#: The worker passes the backend as a CLI flag, not an environment variable.
ATTENTION_BACKEND_FLAG = "--attention-config.backend"

#: Cards Logos runs on, and the attention backend each must end up with.
#: None means "no override" — vLLM picks, which is correct from Ampere on.
BACKEND_BY_PROFILE = {
    "rtx2080ti": "TRITON_ATTN",  # sm75
    "quadro_rtx5000": "TRITON_ATTN",  # sm75
    "a100_80": None,  # sm80
    "rtx_a6000": None,  # sm86
    "l40s": None,  # sm89
    "rtx6000ada": None,  # sm89
    "h100_80": None,  # sm90
}


@pytest.fixture
def spawned(gpu_sim, lane):
    """Spawn one lane on *scenario* and return (env, handle) after readiness."""

    async def _spawn(scenario: GpuScenario, script: VllmScript | None = None, **lane_kwargs):
        env = gpu_sim(scenario, script)
        ctx = lane(**lane_kwargs)
        handle = await ctx.__aenter__()
        return env, handle, ctx

    return _spawn


@pytest.mark.parametrize("profile_key", sorted(BACKEND_BY_PROFILE))
async def test_attention_backend_matches_compute_capability(profile_key, spawned):
    env, handle, ctx = await spawned(GpuScenario.homogeneous(profile_key, 1))
    try:
        await handle.spawn(lane_harness.lane_config())

        profile = GpuProfile.load(profile_key)
        expected = BACKEND_BY_PROFILE[profile_key]
        actual = env.arg_value(ATTENTION_BACKEND_FLAG)
        assert actual == expected, (
            f"{profile.name} (sm{profile.compute_cap}) got attention backend " f"{actual!r}, expected {expected!r}"
        )
    finally:
        await ctx.__aexit__(None, None, None)


async def test_arch_list_is_passed_through_to_the_build(spawned):
    """TORCH_CUDA_ARCH_LIST must carry the card's real capability.

    A wrong value here does not fail loudly — it silently compiles kernels for
    the wrong architecture and costs a full recompile on every start.
    """
    env, handle, ctx = await spawned(GpuScenario.homogeneous("l40s", 1))
    try:
        await handle.spawn(lane_harness.lane_config())
        assert env.last_env().get("TORCH_CUDA_ARCH_LIST") == "8.9"
    finally:
        await ctx.__aexit__(None, None, None)


async def test_mixed_architecture_node_gets_no_backend_override(spawned):
    """A node with one pre-Ampere and one Ampere card must not be forced to Triton.

    ``_auto_attention_backend`` only overrides when *every* card is pre-Ampere.
    Forcing TRITON_ATTN on the mixed node would needlessly slow the newer card;
    the sm75 card is handled by not scheduling FlashInfer work onto it.
    """
    env, handle, ctx = await spawned(GpuScenario(profiles=["rtx2080ti", "l40s"]))
    try:
        await handle.spawn(lane_harness.lane_config())
        assert env.arg_value(ATTENTION_BACKEND_FLAG) is None
        assert env.last_env().get("TORCH_CUDA_ARCH_LIST") == "7.5;8.9"
    finally:
        await ctx.__aexit__(None, None, None)


async def test_explicit_backend_override_wins_over_autodetection(spawned):
    """An operator override must survive the pre-Ampere auto-selection."""
    env, handle, ctx = await spawned(GpuScenario.homogeneous("rtx2080ti", 1))
    try:
        await handle.spawn(lane_harness.lane_config(attention_backend="FLASHINFER"))
        assert env.arg_value(ATTENTION_BACKEND_FLAG) == "FLASHINFER"
    finally:
        await ctx.__aexit__(None, None, None)


async def test_tensor_parallel_lane_claims_every_device(spawned):
    """A TP=2 lane must hold VRAM on both cards, not twice on one.

    The capacity planner's placement arithmetic depends on this, and the sim
    tracks it per device so a regression shows up as a ledger imbalance rather
    than as a mysterious OOM on a real node.
    """
    env, handle, ctx = await spawned(GpuScenario.homogeneous("l40s", 2))
    try:
        await handle.spawn(lane_harness.lane_config(tensor_parallel_size=2, gpu_memory_utilization=0.8))

        assert env.arg_value("--tensor-parallel-size") == "2"
        total = GpuProfile.load("l40s").memory_total_mb
        for device_index in (0, 1):
            assert env.used_mb(device_index) == pytest.approx(total * 0.8, rel=0.01)
    finally:
        await ctx.__aexit__(None, None, None)


async def test_nccl_p2p_disabled_by_default_on_pcie_nodes(spawned):
    """The fleet is PCIe-only; leaving P2P on there hangs NCCL at TP>1."""
    env, handle, ctx = await spawned(GpuScenario.homogeneous("l40s", 2))
    try:
        await handle.spawn(lane_harness.lane_config(tensor_parallel_size=2))
        worker_env = env.last_env()
        assert worker_env.get("NCCL_P2P_DISABLE") == "1"
        assert worker_env.get("TORCH_NCCL_ASYNC_ERROR_HANDLING") == "1"
    finally:
        await ctx.__aexit__(None, None, None)
