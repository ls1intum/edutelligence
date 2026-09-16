"""Drive a real ``VllmProcessHandle`` against the GPU simulator.

Tier 1's whole premise is that no worker code is stubbed: the object under test
is the production one, and only the world below it — nvidia-smi, nvcc, the vLLM
binary — is simulated. This module is the small amount of wiring that takes:
a free port, a temporary persistent-cache root, and teardown that does not leave
orphan processes behind when a test fails mid-spawn.
"""

from __future__ import annotations

import contextlib
import socket
from pathlib import Path
from typing import Any, AsyncIterator

from logos_worker_node.models import LaneConfig, VllmConfig, VllmEngineConfig, WorkerConfig
from logos_worker_node.vllm_process import VllmProcessHandle

#: A small, real model id. Nothing is downloaded — the fake vLLM never touches
#: the Hub — but using a genuine id keeps name-derived behaviour (tool-call
#: parser inference, per-model overrides) on its production path.
DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"


def free_port() -> int:
    """Claim an ephemeral port and hand back its number.

    There is an unavoidable race between closing the probe socket and the fake
    vLLM binding it. Lane ports are otherwise fixed by config, and a collision
    surfaces as a clear bind error rather than a silent pass.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def worker_config(cache_root: Path, **overrides: Any) -> WorkerConfig:
    """A WorkerConfig whose caches all land under *cache_root*.

    Pointing ``models_path``/``cache_path`` at a temp directory is what makes
    the compile-cache purge paths observable: a test can list what survived.
    """
    values: dict[str, Any] = {
        "models_path": str(cache_root / "models"),
        "cache_path": str(cache_root / "cache"),
        "gpu_devices": "all",
    }
    values.update(overrides)
    return WorkerConfig(**values)


def lane_config(model: str = DEFAULT_MODEL, **vllm_overrides: Any) -> LaneConfig:
    return LaneConfig(model=model, vllm_config=VllmConfig(**vllm_overrides))


@contextlib.asynccontextmanager
async def lane(
    cache_root: Path,
    *,
    lane_id: str = "lane-0",
    port: int | None = None,
    engine_config: VllmEngineConfig | None = None,
    worker_overrides: dict[str, Any] | None = None,
) -> AsyncIterator[VllmProcessHandle]:
    """Yield an initialised handle and guarantee the process is gone afterwards."""
    handle = VllmProcessHandle(
        lane_id=lane_id,
        port=port or free_port(),
        global_config=worker_config(cache_root, **(worker_overrides or {})),
        vllm_engine_config=engine_config or VllmEngineConfig(),
    )
    await handle.init()
    try:
        yield handle
    finally:
        with contextlib.suppress(Exception):
            await handle.destroy()
        with contextlib.suppress(Exception):
            await handle.close()


async def try_spawn(handle: VllmProcessHandle, config: LaneConfig) -> BaseException | None:
    """Spawn and return the exception instead of raising it.

    Startup-failure tests care about *which* failure the worker reached and what
    it did about it, not about the raise itself — this keeps them from being a
    wall of ``pytest.raises`` blocks that hide the interesting assertion.
    """
    try:
        await handle.spawn(config)
    except BaseException as exc:  # noqa: BLE001 - the failure is the subject
        return exc
    return None
