"""Scenario definitions: what hardware exists, and how vLLM misbehaves on it.

A :class:`GpuScenario` describes the machine (which cards, how many, how much
VRAM already in use). A :class:`VllmScript` describes what the fake vLLM does
when the worker spawns it — become ready, hang, crash with a particular log,
leak VRAM, wedge its EngineCore.

Both are plain dataclasses that round-trip through JSON so the shims (separate
processes, no shared memory) can read exactly what the test wrote.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.gpusim.state import Device, GpuSimState, SmiBehaviour

PROFILES_DIR = Path(__file__).parent / "profiles"

SCRIPT_ENV_VAR = "LOGOS_GPUSIM_VLLM_SCRIPT"


# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------


@dataclass
class GpuProfile:
    """One GPU model, as nvidia-smi describes it.

    Loaded from ``profiles/*.json``. The values are the ones that drive real
    decisions — ``compute_cap`` selects the attention backend, ``memory.total``
    drives the capacity planner — so they are kept faithful to the cards Logos
    actually runs on rather than rounded off.
    """

    key: str
    name: str
    compute_cap: str
    memory_total_mb: float
    idle_power_w: float = 30.0
    idle_temp_c: float = 35.0
    fan_speed: str = "30"

    @classmethod
    def load(cls, key: str) -> "GpuProfile":
        path = PROFILES_DIR / f"{key}.json"
        if not path.is_file():
            available = ", ".join(sorted(p.stem for p in PROFILES_DIR.glob("*.json")))
            raise FileNotFoundError(f"No GPU profile {key!r}. Available: {available}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(key=key, **raw)

    @classmethod
    def all_keys(cls) -> list[str]:
        return sorted(p.stem for p in PROFILES_DIR.glob("*.json"))

    def device(self, index: int) -> Device:
        return Device(
            index=index,
            fields={
                "index": str(index),
                "uuid": f"GPU-{self.key}-{index:04d}-0000-000000000000",
                "name": self.name,
                "compute_cap": self.compute_cap,
                "memory.total": str(int(self.memory_total_mb)),
                "utilization.gpu": "0",
                "temperature.gpu": str(int(self.idle_temp_c)),
                "power.draw": f"{self.idle_power_w:.2f}",
                "fan.speed": self.fan_speed,
                "pci.bus_id": f"00000000:{index + 1:02X}:00.0",
            },
        )


@dataclass
class GpuScenario:
    """A machine: N cards of one or more profiles, plus nvidia-smi's own health."""

    profiles: list[str]
    baseline_used_mb: float = 0.0
    smi: SmiBehaviour = field(default_factory=SmiBehaviour)
    driver_version: str = "560.35.03"
    cuda_version: str = "12.6"

    @classmethod
    def homogeneous(cls, profile: str, count: int = 1, **kwargs: Any) -> "GpuScenario":
        return cls(profiles=[profile] * count, **kwargs)

    @classmethod
    def headless(cls, **kwargs: Any) -> "GpuScenario":
        """No GPUs and no working nvidia-smi — a developer laptop or a CI runner."""
        return cls(profiles=[], smi=SmiBehaviour(absent=True), **kwargs)

    def to_state(self) -> GpuSimState:
        devices = []
        for index, profile_key in enumerate(self.profiles):
            device = GpuProfile.load(profile_key).device(index)
            device.baseline_used_mb = self.baseline_used_mb
            devices.append(device)
        return GpuSimState(
            devices=devices,
            smi=self.smi,
            driver_version=self.driver_version,
            cuda_version=self.cuda_version,
        )


# ---------------------------------------------------------------------------
# vLLM behaviour
# ---------------------------------------------------------------------------


@dataclass
class VllmScript:
    """What the fake vLLM does for one lane.

    Defaults describe a healthy lane: it prints a plausible startup banner,
    allocates VRAM proportional to ``--gpu-memory-utilization``, serves, and
    gives the memory back when it is killed.
    """

    #: Seconds between spawn and /health answering 200.
    ready_after_s: float = 0.2
    #: Corpus file (relative to ``harness/corpus``) to print before anything
    #: else. The worker classifies failures from this log blob.
    emit_log: str | None = None
    #: Exit with this code after emitting the log, instead of serving. A lane
    #: that never becomes ready is how every startup failure presents.
    exit_code: int | None = None
    #: Override the VRAM to claim. ``None`` derives it from the
    #: ``--gpu-memory-utilization`` on the command line, which is what makes
    #: the planner's arithmetic observable.
    vram_mb: float | None = None
    #: Exit without giving VRAM back — a stuck CUDA context.
    leak_vram: bool = False
    #: ``/sleep`` returns 500.
    refuse_sleep: bool = False
    #: Seconds ``/wake_up`` takes to answer.
    slow_wake_s: float = 0.0
    #: ``/health`` and ``/v1/models`` answer 200 while ``/is_sleeping`` never
    #: returns — the real wedge where the API server outlives its EngineCore.
    wedge_engine_core: bool = False
    #: Reported in vLLM's "Maximum concurrency for N tokens per request: Xx"
    #: startup line, which the worker parses for lane capacity.
    max_concurrency: float = 8.0
    max_concurrency_tokens: int = 32768
    #: Emit vLLM's dev-mode security warning, which the worker is expected to
    #: suppress from its own log stream.
    emit_dev_mode_warning: bool = True
    #: Per-model overrides, applied when the spawned model matches. Lets one
    #: multi-lane scenario fail exactly one model.
    per_model: dict[str, dict[str, Any]] = field(default_factory=dict)

    def for_model(self, model: str) -> "VllmScript":
        override = self.per_model.get(model)
        if not override:
            return self
        merged = {**self.to_json(), **override}
        merged.pop("per_model", None)
        return VllmScript(**merged)

    def to_json(self) -> dict[str, Any]:
        return {
            "ready_after_s": self.ready_after_s,
            "emit_log": self.emit_log,
            "exit_code": self.exit_code,
            "vram_mb": self.vram_mb,
            "leak_vram": self.leak_vram,
            "refuse_sleep": self.refuse_sleep,
            "slow_wake_s": self.slow_wake_s,
            "wedge_engine_core": self.wedge_engine_core,
            "max_concurrency": self.max_concurrency,
            "max_concurrency_tokens": self.max_concurrency_tokens,
            "emit_dev_mode_warning": self.emit_dev_mode_warning,
            "per_model": dict(self.per_model),
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "VllmScript":
        known = {f for f in cls().to_json()}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def write(self, path: str | os.PathLike[str]) -> None:
        Path(path).write_text(json.dumps(self.to_json(), indent=2), encoding="utf-8")

    @classmethod
    def read(cls, path: str | os.PathLike[str] | None = None) -> "VllmScript":
        resolved = str(path) if path is not None else os.environ.get(SCRIPT_ENV_VAR, "")
        if not resolved or not Path(resolved).is_file():
            return cls()
        return cls.from_json(json.loads(Path(resolved).read_text(encoding="utf-8")))
