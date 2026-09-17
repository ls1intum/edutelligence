"""Mutable world-state for the GPU simulator.

A single JSON file (``$LOGOS_GPUSIM_STATE``) is the world every part of the
simulator agrees on:

* the ``nvidia-smi`` shim renders it into whatever CSV the caller asked for,
* the fake vLLM server debits VRAM from it on start and credits it back on a
  clean exit,
* tests mutate it mid-run to inject faults (a GSP wedge, a card falling off the
  bus, a driver that stops answering).

That shared ledger is what makes the sim more than canned output: the capacity
planner sees VRAM actually move, and a process that exits *without* crediting
its allocation back reproduces a stuck CUDA context exactly as
``VllmProcessHandle._verify_vram_released`` observes one — through
``nvidia-smi --query-compute-apps``.

Field names are nvidia-smi's own (``memory.total``, ``power.draw``,
``compute_cap``, …) so the shim can stay generic: it never needs to know which
fields exist, only how to look them up.
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

STATE_ENV_VAR = "LOGOS_GPUSIM_STATE"

#: Tokens nvidia-smi emits for a field it cannot read. ``node_health`` treats
#: these differently per field group, so the sim must be able to produce each
#: one verbatim.
ERROR_TOKENS = ("ERR!", "[Error]", "[N/A]", "N/A", "[Unknown Error]")

#: Fields derived from the ledger rather than stored, so a test that sets
#: ``memory.used`` directly does not silently disagree with the allocations.
DERIVED_FIELDS = ("memory.used", "memory.free")


class GpuSimStateError(RuntimeError):
    """Raised when the state file is missing or unreadable."""


@dataclass
class Allocation:
    """VRAM held by one process on one device."""

    pid: int
    device_index: int
    mb: float
    #: When True, ``release`` leaves this allocation in place — the process is
    #: gone but the driver never reclaimed the context.
    leaked: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"pid": self.pid, "device_index": self.device_index, "mb": self.mb, "leaked": self.leaked}

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Allocation":
        return cls(
            pid=int(raw["pid"]),
            device_index=int(raw.get("device_index", 0)),
            mb=float(raw["mb"]),
            leaked=bool(raw.get("leaked", False)),
        )


@dataclass
class Device:
    """One simulated GPU.

    ``fields`` holds the static nvidia-smi values; ``faults`` overrides any of
    them with a literal error token at render time. Keeping faults separate
    means a test can wedge and un-wedge a card without losing what the healthy
    values were.
    """

    index: int
    fields: dict[str, str] = field(default_factory=dict)
    faults: dict[str, str] = field(default_factory=dict)
    #: VRAM in use before any simulated lane starts (driver overhead, the
    #: desktop compositor, another tenant).
    baseline_used_mb: float = 0.0
    #: The card is not enumerated at all — a PCIe drop. It disappears from
    #: every query rather than reporting errors.
    absent: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "fields": dict(self.fields),
            "faults": dict(self.faults),
            "baseline_used_mb": self.baseline_used_mb,
            "absent": self.absent,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Device":
        return cls(
            index=int(raw["index"]),
            fields=dict(raw.get("fields", {})),
            faults=dict(raw.get("faults", {})),
            baseline_used_mb=float(raw.get("baseline_used_mb", 0.0)),
            absent=bool(raw.get("absent", False)),
        )

    @property
    def memory_total_mb(self) -> float:
        try:
            return float(self.fields.get("memory.total", 0) or 0)
        except ValueError:
            return 0.0


@dataclass
class SmiBehaviour:
    """How the ``nvidia-smi`` binary itself behaves, independent of the cards."""

    #: The binary is not on PATH at all (a dev host, a container without the
    #: NVIDIA runtime). The shim removes itself from consideration by exiting
    #: 127, and ``GpuSimEnv`` can also omit it from PATH entirely.
    absent: bool = False
    exit_code: int = 0
    stderr: str = ""
    #: Sleep this long before answering. Callers use timeouts of 5-30s, so a
    #: value above those reproduces a wedged driver.
    hang_seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "absent": self.absent,
            "exit_code": self.exit_code,
            "stderr": self.stderr,
            "hang_seconds": self.hang_seconds,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "SmiBehaviour":
        return cls(
            absent=bool(raw.get("absent", False)),
            exit_code=int(raw.get("exit_code", 0)),
            stderr=str(raw.get("stderr", "")),
            hang_seconds=float(raw.get("hang_seconds", 0.0)),
        )


@dataclass
class GpuSimState:
    """The whole simulated machine."""

    devices: list[Device] = field(default_factory=list)
    allocations: list[Allocation] = field(default_factory=list)
    smi: SmiBehaviour = field(default_factory=SmiBehaviour)
    driver_version: str = "560.35.03"
    cuda_version: str = "12.6"
    #: Every ``vllm`` invocation the shim saw, in order. Tests assert on the
    #: command line the worker *built* — that is where GPU-compat decisions
    #: (attention backend, TP size, arch list) actually materialise.
    vllm_invocations: list[dict[str, Any]] = field(default_factory=list)

    # -- serialisation ----------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "devices": [d.to_json() for d in self.devices],
            "allocations": [a.to_json() for a in self.allocations],
            "smi": self.smi.to_json(),
            "driver_version": self.driver_version,
            "cuda_version": self.cuda_version,
            "vllm_invocations": list(self.vllm_invocations),
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "GpuSimState":
        return cls(
            devices=[Device.from_json(d) for d in raw.get("devices", [])],
            allocations=[Allocation.from_json(a) for a in raw.get("allocations", [])],
            smi=SmiBehaviour.from_json(raw.get("smi", {})),
            driver_version=str(raw.get("driver_version", "560.35.03")),
            cuda_version=str(raw.get("cuda_version", "12.6")),
            vllm_invocations=list(raw.get("vllm_invocations", [])),
        )

    # -- queries ----------------------------------------------------------

    def visible_devices(self) -> list[Device]:
        return [d for d in self.devices if not d.absent]

    def device(self, index: int) -> Device | None:
        for dev in self.devices:
            if dev.index == index:
                return dev
        return None

    def used_mb(self, device_index: int) -> float:
        dev = self.device(device_index)
        base = dev.baseline_used_mb if dev else 0.0
        return base + sum(a.mb for a in self.allocations if a.device_index == device_index)

    def free_mb(self, device_index: int) -> float:
        dev = self.device(device_index)
        total = dev.memory_total_mb if dev else 0.0
        return max(total - self.used_mb(device_index), 0.0)

    def field_value(self, dev: Device, name: str) -> str:
        """Render one nvidia-smi field for one device, honouring faults."""
        if name in dev.faults:
            return dev.faults[name]
        if name == "memory.used":
            return _fmt(self.used_mb(dev.index))
        if name == "memory.free":
            return _fmt(self.free_mb(dev.index))
        if name == "driver_version":
            return self.driver_version
        return dev.fields.get(name, "[Not Supported]")

    # -- mutation ---------------------------------------------------------

    def allocate(self, pid: int, device_index: int, mb: float) -> None:
        self.allocations.append(Allocation(pid=pid, device_index=device_index, mb=mb))

    def release(self, pid: int) -> None:
        """Free every non-leaked allocation held by *pid*.

        Leaked allocations survive on purpose: that is the stuck-CUDA-context
        signature the worker detects after a kill.
        """
        self.allocations = [a for a in self.allocations if a.pid != pid or a.leaked]

    def mark_leaked(self, pid: int) -> None:
        for alloc in self.allocations:
            if alloc.pid == pid:
                alloc.leaked = True

    def wedge_device(self, index: int, *, token: str = "ERR!") -> None:
        """Reproduce the GSP RPC failure: memory still reads, telemetry does not.

        This is the RTX 6000 Ada / Quadro RTX 5000 signature documented in
        ``gpu_watchdog`` — the card answers memory queries fine while Pwr / Fan /
        Temp flip to ``ERR!`` and every CUDA context allocation afterwards
        fails.
        """
        dev = self.device(index)
        if dev is None:
            raise KeyError(f"no simulated device with index {index}")
        for name in ("power.draw", "fan.speed", "temperature.gpu"):
            dev.faults[name] = token

    def unwedge_device(self, index: int) -> None:
        dev = self.device(index)
        if dev is not None:
            dev.faults.clear()


def _fmt(value: float) -> str:
    """nvidia-smi renders memory as a bare integer under ``nounits``."""
    return str(int(round(value)))


# ---------------------------------------------------------------------------
# File access
# ---------------------------------------------------------------------------


def state_path(path: str | os.PathLike[str] | None = None) -> Path:
    resolved = str(path) if path is not None else os.environ.get(STATE_ENV_VAR, "")
    if not resolved:
        raise GpuSimStateError(
            f"{STATE_ENV_VAR} is not set — the GPU simulator needs a state file. "
            "Use the `gpu_sim` pytest fixture, or set the variable yourself."
        )
    return Path(resolved)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock for the duration of a read-modify-write.

    The shim, the fake server and the test process all touch this file
    concurrently; without the lock a lane starting while another is stopping
    can lose an allocation and produce a phantom VRAM leak.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load(path: str | os.PathLike[str] | None = None) -> GpuSimState:
    resolved = state_path(path)
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GpuSimStateError(f"GPU simulator state file not found: {resolved}") from exc
    except json.JSONDecodeError as exc:
        raise GpuSimStateError(f"GPU simulator state file is not valid JSON: {resolved}") from exc
    return GpuSimState.from_json(raw)


def save(state: GpuSimState, path: str | os.PathLike[str] | None = None) -> None:
    resolved = state_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    tmp.write_text(json.dumps(state.to_json(), indent=2), encoding="utf-8")
    tmp.replace(resolved)


@contextmanager
def mutate(path: str | os.PathLike[str] | None = None) -> Iterator[GpuSimState]:
    """Read-modify-write the state under an exclusive lock."""
    resolved = state_path(path)
    with _locked(resolved):
        state = load(resolved)
        yield state
        save(state, resolved)
