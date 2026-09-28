"""Assembles a runnable GPU-simulator environment.

A :class:`GpuSimEnv` is a temporary directory holding the world-state file, the
vLLM behaviour script, and a ``bin/`` directory of shims. Point ``PATH`` and
``LOGOS_GPUSIM_STATE`` at it and the worker — unmodified — talks to simulated
hardware.

Two PATH modes, because "the tool is missing" is itself a scenario:

``prepend``
    The shims shadow the real tools but the inherited ``PATH`` still follows.
    Fine for almost everything, and keeps ordinary system utilities reachable.

``isolated``
    ``PATH`` contains only the shim directory plus an explicit allowlist of
    system binaries symlinked into it. This is the only way to make
    ``shutil.which("gcc")`` genuinely fail, which is what the nvcc / C-compiler
    preflight tests need.
"""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from harness.gpusim import state as gpustate
from harness.gpusim.scenario import GpuScenario, VllmScript

SHIM_DIR = Path(__file__).parent / "bin"

#: Every shim the simulator can install. A scenario omits one to make the
#: corresponding tool missing.
ALL_TOOLS = ("nvidia-smi", "vllm", "nvcc", "cc", "gcc")

#: System binaries linked into an isolated PATH. The worker shells out to these
#: on best-effort paths (process-tree walks, watchdog diagnostics); leaving them
#: out would test a failure nobody is asking about.
ISOLATED_PASSTHROUGH = ("python3", "sh", "env", "pgrep", "ps", "kill", "dmesg", "uname")


@dataclass
class GpuSimEnv:
    root: Path
    bin_dir: Path
    state_file: Path
    script_file: Path
    path_mode: str = "prepend"

    # -- environment ------------------------------------------------------

    def path_value(self) -> str:
        if self.path_mode == "isolated":
            return str(self.bin_dir)
        return os.pathsep.join([str(self.bin_dir), os.environ.get("PATH", "")])

    def env(self) -> dict[str, str]:
        """Variables to apply to the process (or container) under test."""
        return {
            "PATH": self.path_value(),
            gpustate.STATE_ENV_VAR: str(self.state_file),
            "LOGOS_GPUSIM_VLLM_SCRIPT": str(self.script_file),
        }

    def apply(self, monkeypatch) -> "GpuSimEnv":
        """Install this environment into the current process via monkeypatch."""
        for key, value in self.env().items():
            monkeypatch.setenv(key, value)
        # The worker caches the detected arch on the class, so a second test
        # with different hardware would otherwise inherit the first one's answer.
        self.reset_arch_cache()
        return self

    @staticmethod
    def reset_arch_cache() -> None:
        try:
            from logos_worker_node.vllm_process import VllmProcessHandle  # noqa: PLC0415
        except ImportError:
            return
        VllmProcessHandle._cached_cuda_arch = None

    # -- state ------------------------------------------------------------

    def state(self) -> gpustate.GpuSimState:
        return gpustate.load(self.state_file)

    @contextmanager
    def mutate(self) -> Iterator[gpustate.GpuSimState]:
        with gpustate.mutate(self.state_file) as sim:
            yield sim

    def set_script(self, script: VllmScript) -> None:
        script.write(self.script_file)

    # -- recorded invocations --------------------------------------------

    def invocations(self) -> list[dict]:
        return self.state().vllm_invocations

    def last_invocation(self) -> dict:
        recorded = self.invocations()
        if not recorded:
            raise AssertionError("the worker never spawned vLLM — no invocation was recorded")
        return recorded[-1]

    def last_argv(self) -> list[str]:
        return self.last_invocation()["argv"]

    def last_env(self) -> dict[str, str]:
        return self.last_invocation()["env"]

    def arg_value(self, flag: str) -> str | None:
        """Value of ``--flag`` in the most recent invocation, or None."""
        argv = self.last_argv()
        for index, arg in enumerate(argv):
            if arg == flag and index + 1 < len(argv):
                return argv[index + 1]
            if arg.startswith(f"{flag}="):
                return arg.split("=", 1)[1]
        return None

    # -- VRAM -------------------------------------------------------------

    def used_mb(self, device_index: int = 0) -> float:
        return self.state().used_mb(device_index)

    def free_mb(self, device_index: int = 0) -> float:
        return self.state().free_mb(device_index)

    def leaked_pids(self) -> set[int]:
        return {a.pid for a in self.state().allocations if a.leaked}


def build(
    root: str | os.PathLike[str],
    scenario: GpuScenario,
    script: VllmScript | None = None,
    *,
    tools: Sequence[str] = ALL_TOOLS,
    path_mode: str = "prepend",
) -> GpuSimEnv:
    """Materialise *scenario* under *root* and return the handle.

    *tools* is the set of shims to install; dropping ``"nvcc"`` reproduces a
    container without CUDA toolkit visibility, dropping ``"nvidia-smi"``
    reproduces a host with no NVIDIA runtime (callers see ``FileNotFoundError``,
    which is a different code path from a non-zero exit).
    """
    if path_mode not in ("prepend", "isolated"):
        raise ValueError(f"path_mode must be 'prepend' or 'isolated', got {path_mode!r}")

    root_path = Path(root)
    bin_dir = root_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    unknown = set(tools) - set(ALL_TOOLS)
    if unknown:
        raise ValueError(f"unknown tool(s) {sorted(unknown)}; known: {list(ALL_TOOLS)}")

    for tool in tools:
        source = SHIM_DIR / tool
        target = bin_dir / tool
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(source)

    if path_mode == "isolated":
        _link_passthrough(bin_dir)

    state_file = root_path / "gpusim.json"
    gpustate.save(scenario.to_state(), state_file)

    script_file = root_path / "vllm_script.json"
    (script or VllmScript()).write(script_file)

    return GpuSimEnv(
        root=root_path,
        bin_dir=bin_dir,
        state_file=state_file,
        script_file=script_file,
        path_mode=path_mode,
    )


def _link_passthrough(bin_dir: Path) -> None:
    """Symlink the allowlisted system binaries into an isolated bin directory."""
    for name in ISOLATED_PASSTHROUGH:
        target = bin_dir / name
        if target.exists() or target.is_symlink():
            continue
        located = shutil.which(name)
        if name == "python3" and not located:
            located = sys.executable
        if located:
            target.symlink_to(located)
