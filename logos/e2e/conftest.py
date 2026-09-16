"""Shared fixtures for the Logos E2E suite.

Tier 1 imports ``logos_worker_node`` straight from the sibling working tree —
the point of the suite is to drive the real worker, not a copy of it — so the
path is wired up here rather than depending on an install step.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

E2E_ROOT = Path(__file__).resolve().parent
LOGOS_ROOT = E2E_ROOT.parent
WORKERNODE_ROOT = LOGOS_ROOT / "logos-workernode"
ORCHESTRATOR_SRC = LOGOS_ROOT / "logos-orchestrator" / "src"

for candidate in (E2E_ROOT, WORKERNODE_ROOT, ORCHESTRATOR_SRC):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from harness.gpusim import env as gpusim_env  # noqa: E402
from harness.gpusim.scenario import GpuScenario, VllmScript  # noqa: E402


@pytest.fixture
def gpu_sim(tmp_path, monkeypatch):
    """A builder for simulated GPU environments.

    Call it with a scenario (and optionally a vLLM behaviour script) to get a
    :class:`~harness.gpusim.env.GpuSimEnv` with ``PATH`` and the state-file
    variables already applied to this process:

        env = gpu_sim(GpuScenario.homogeneous("l40s", 2))
        assert env.arg_value("--tensor-parallel-size") == "2"

    Defaults to a single L40S, which is the most common card in the fleet.
    """
    created: list[gpusim_env.GpuSimEnv] = []

    def _build(
        scenario: GpuScenario | None = None,
        script: VllmScript | None = None,
        *,
        tools=gpusim_env.ALL_TOOLS,
        path_mode: str = "prepend",
    ) -> gpusim_env.GpuSimEnv:
        root = tmp_path / f"gpusim-{len(created)}"
        built = gpusim_env.build(
            root,
            scenario or GpuScenario.homogeneous("l40s", 1),
            script,
            tools=tools,
            path_mode=path_mode,
        )
        built.apply(monkeypatch)
        created.append(built)
        return built

    yield _build

    # The worker caches the detected compute capability on the class for the
    # lifetime of the process; leaving it set would leak this test's hardware
    # into the next one.
    gpusim_env.GpuSimEnv.reset_arch_cache()
