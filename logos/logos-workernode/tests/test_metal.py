"""Tests for the Metal telemetry collector and its macOS memory helpers.

Every OS interaction is mocked, so these run identically on the Linux CI
runners and on a developer's Mac.
"""

from __future__ import annotations

import os
import subprocess
from unittest.mock import patch

import pytest

from logos_worker_node import metal

# Real `vm_stat` output from an M3 Pro, trimmed. Note the 16 KiB page size —
# assuming the x86 default of 4 KiB would understate every figure by 4×.
VM_STAT_SAMPLE = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                   117985.
Pages active:                                 811307.
Pages inactive:                               793711.
Pages speculative:                             23743.
Pages throttled:                                   0.
Pages wired down:                             218557.
Pages purgeable:                               44083.
"Translation faults":                     2001378913.
Pages copy-on-write:                       109717097.
"""

PAGE = 16384


def _fake_run(mapping: dict[str, str]):
    """Return a _run replacement that answers by command prefix."""

    def _inner(cmd: list[str], timeout: int = 10) -> str | None:
        key = " ".join(cmd)
        for prefix, value in mapping.items():
            if key.startswith(prefix):
                return value
        return None

    return _inner


class TestParseVmStat:
    def test_applies_the_announced_page_size(self) -> None:
        stats = metal.parse_vm_stat(VM_STAT_SAMPLE)
        assert stats is not None
        assert stats["Pages free"] == 117985 * PAGE
        assert stats["Pages wired down"] == 218557 * PAGE

    def test_parses_quoted_labels(self) -> None:
        stats = metal.parse_vm_stat(VM_STAT_SAMPLE)
        assert stats is not None
        assert stats["Translation faults"] == 2001378913 * PAGE

    def test_returns_none_without_a_page_size_header(self) -> None:
        assert metal.parse_vm_stat("Pages free: 100.") is None

    def test_returns_none_on_empty_input(self) -> None:
        assert metal.parse_vm_stat("") is None


class TestReadHostMemoryMb:
    def test_available_counts_reclaimable_pages(self) -> None:
        with (
            patch.object(metal, "_run", _fake_run({"sysctl -n hw.memsize": "38654705664"})),
            patch.object(metal, "read_vm_stat", return_value=metal.parse_vm_stat(VM_STAT_SAMPLE)),
        ):
            result = metal.read_host_memory_mb()
        assert result is not None
        total_mb, used_mb, available_mb = result
        assert total_mb == pytest.approx(36864, abs=1)
        # free + inactive + speculative + purgeable, mirroring MemAvailable.
        expected = (117985 + 793711 + 23743 + 44083) * PAGE / 1024**2
        assert available_mb == pytest.approx(expected, abs=1)
        assert used_mb == pytest.approx(total_mb - available_mb, abs=1)

    def test_available_never_exceeds_total(self) -> None:
        """A tiny hw.memsize must not yield more available than exists."""
        with (
            patch.object(metal, "_run", _fake_run({"sysctl -n hw.memsize": "1048576"})),
            patch.object(metal, "read_vm_stat", return_value=metal.parse_vm_stat(VM_STAT_SAMPLE)),
        ):
            total_mb, used_mb, available_mb = metal.read_host_memory_mb()
        assert available_mb <= total_mb
        assert used_mb >= 0.0

    def test_returns_none_when_sysctl_fails(self) -> None:
        with (
            patch.object(metal, "_run", lambda *a, **k: None),
            patch.object(metal, "read_vm_stat", return_value=metal.parse_vm_stat(VM_STAT_SAMPLE)),
        ):
            assert metal.read_host_memory_mb() is None

    def test_returns_none_when_vm_stat_fails(self) -> None:
        with (
            patch.object(metal, "_run", _fake_run({"sysctl -n hw.memsize": "38654705664"})),
            patch.object(metal, "read_vm_stat", return_value=None),
        ):
            assert metal.read_host_memory_mb() is None


class TestReadSwapMb:
    def test_parses_sysctl_swapusage(self) -> None:
        raw = "total = 2048.00M  used = 512.25M  free = 1535.75M  (encrypted)"
        with patch.object(metal, "_run", _fake_run({"sysctl -n vm.swapusage": raw})):
            total, used = metal.read_swap_mb()
        assert total == pytest.approx(2048.0)
        assert used == pytest.approx(512.25)

    def test_handles_gigabyte_units(self) -> None:
        raw = "total = 4.00G  used = 1.50G  free = 2.50G"
        with patch.object(metal, "_run", _fake_run({"sysctl -n vm.swapusage": raw})):
            total, used = metal.read_swap_mb()
        assert total == pytest.approx(4096.0)
        assert used == pytest.approx(1536.0)

    def test_returns_zeros_when_unavailable(self) -> None:
        with patch.object(metal, "_run", lambda *a, **k: None):
            assert metal.read_swap_mb() == (0.0, 0.0)


class TestReadProcessRssMb:
    def test_converts_ps_kib_to_mib(self) -> None:
        with patch.object(metal, "_run", _fake_run({"ps -o rss=": " 1048576\n"})):
            assert metal.read_process_rss_mb(123) == pytest.approx(1024.0)

    def test_returns_zero_for_a_dead_pid(self) -> None:
        with patch.object(metal, "_run", lambda *a, **k: None):
            assert metal.read_process_rss_mb(999999) == 0.0

    def test_returns_zero_on_unparseable_output(self) -> None:
        with patch.object(metal, "_run", _fake_run({"ps -o rss=": "not-a-number"})):
            assert metal.read_process_rss_mb(1) == 0.0


class TestIsMetalBackend:
    def test_follows_the_platform_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv("LOGOS_WORKER_BACKEND", raising=False)
        monkeypatch.setattr(metal.sys, "platform", "darwin")
        assert metal.is_metal_backend() is True
        monkeypatch.setattr(metal.sys, "platform", "linux")
        assert metal.is_metal_backend() is False

    @pytest.mark.parametrize(
        ("override", "platform", "expected"),
        [
            ("metal", "linux", True),
            ("cuda", "darwin", False),
            ("METAL", "linux", True),
            ("  cuda  ", "darwin", False),
        ],
    )
    def test_env_override_wins(self, monkeypatch, override, platform, expected) -> None:
        monkeypatch.setenv("LOGOS_WORKER_BACKEND", override)
        monkeypatch.setattr(metal.sys, "platform", platform)
        assert metal.is_metal_backend() is expected

    def test_nonsense_override_falls_back_to_platform(self, monkeypatch) -> None:
        monkeypatch.setenv("LOGOS_WORKER_BACKEND", "rocm")
        monkeypatch.setattr(metal.sys, "platform", "darwin")
        assert metal.is_metal_backend() is True


class TestDefaultMetalVenv:
    """The venv location the installer, the launchd plist and the runtime
    resolvers must all agree on."""

    def test_defaults_to_the_upstream_layout(self, monkeypatch) -> None:
        monkeypatch.delenv("LOGOS_METAL_VENV", raising=False)
        assert metal.default_metal_venv() == os.path.expanduser("~/.venv-vllm-metal")

    def test_honours_LOGOS_METAL_VENV(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("LOGOS_METAL_VENV", str(tmp_path / "custom-venv"))
        assert metal.default_metal_venv() == str(tmp_path / "custom-venv")

    def test_blank_override_falls_back_to_the_default(self, monkeypatch) -> None:
        monkeypatch.setenv("LOGOS_METAL_VENV", "   ")
        assert metal.default_metal_venv() == os.path.expanduser("~/.venv-vllm-metal")

    def test_interpreter_candidates_use_the_venv(self, monkeypatch, tmp_path) -> None:
        # A python inside the custom venv must be probed — the old hard-coded
        # default would have skipped a correctly installed custom location.
        venv_python = tmp_path / "custom-venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("#!/bin/sh\n")
        venv_python.chmod(0o755)
        monkeypatch.setenv("LOGOS_METAL_VENV", str(tmp_path / "custom-venv"))
        assert str(venv_python) in metal.metal_python_candidates("")


class TestProbeDeviceInfo:
    DEVICE_JSON = (
        '{"device_name": "Apple M3 Pro", "architecture": "applegpu_g15s", '
        '"memory_size": 38654705664, "max_recommended_working_set_size": 30150672384, '
        '"max_buffer_length": 22613000192}'
    )

    def test_parses_json_from_the_probe(self) -> None:
        with (
            patch.object(metal, "metal_python_candidates", return_value=["/fake/python"]),
            patch.object(metal, "_run", lambda *a, **k: self.DEVICE_JSON),
        ):
            info = metal.probe_device_info()
        assert info is not None
        assert info["device_name"] == "Apple M3 Pro"
        assert info["max_recommended_working_set_size"] == 30150672384

    def test_ignores_noise_before_the_json(self) -> None:
        """mlx emits deprecation warnings; the JSON is the last line."""
        noisy = f"mx.metal.device_info is deprecated\n{self.DEVICE_JSON}\n"
        with (
            patch.object(metal, "metal_python_candidates", return_value=["/fake/python"]),
            patch.object(metal, "_run", lambda *a, **k: noisy),
        ):
            assert metal.probe_device_info() is not None

    def test_returns_none_when_no_candidate_works(self) -> None:
        with (
            patch.object(metal, "metal_python_candidates", return_value=["/a", "/b"]),
            patch.object(metal, "_run", lambda *a, **k: None),
        ):
            assert metal.probe_device_info() is None

    def test_tries_the_next_candidate_after_a_failure(self) -> None:
        calls: list[str] = []

        def _run(cmd, timeout=10):
            calls.append(cmd[0])
            return self.DEVICE_JSON if cmd[0] == "/good" else None

        with (
            patch.object(metal, "metal_python_candidates", return_value=["/bad", "/good"]),
            patch.object(metal, "_run", _run),
        ):
            assert metal.probe_device_info() is not None
        assert calls == ["/bad", "/good"]


class TestMetalMetricsCollector:
    DEVICE_INFO = {
        "device_name": "Apple M3 Pro",
        "architecture": "applegpu_g15s",
        "max_recommended_working_set_size": 30150672384,
        "max_buffer_length": 22613000192,
    }

    @pytest.mark.asyncio
    async def test_reports_the_metal_working_set_not_total_ram(self) -> None:
        """Total must be the GPU budget, not hw.memsize.

        Reporting 36 GB when Metal will only wire down 28 GB would let the
        planner schedule a lane that cannot become resident.
        """
        collector = metal.MetalMetricsCollector(poll_interval=3600)
        with (
            patch.object(metal, "probe_device_info", return_value=self.DEVICE_INFO),
            patch.object(metal, "read_vm_stat", return_value=metal.parse_vm_stat(VM_STAT_SAMPLE)),
        ):
            await collector.start()
            snapshot = await collector.get_snapshot()
            await collector.stop()

        assert snapshot.total_memory_mb == pytest.approx(30150672384 / 1024**2, abs=1)
        assert snapshot.total_memory_mb < 38654705664 / 1024**2

    @pytest.mark.asyncio
    async def test_snapshot_shape_matches_what_the_orchestrator_reads(self) -> None:
        collector = metal.MetalMetricsCollector(poll_interval=3600)
        with (
            patch.object(metal, "probe_device_info", return_value=self.DEVICE_INFO),
            patch.object(metal, "read_vm_stat", return_value=metal.parse_vm_stat(VM_STAT_SAMPLE)),
        ):
            await collector.start()
            snapshot = await collector.get_snapshot()
            await collector.stop()

        assert snapshot.mode == "metal"
        # Must stay False: it names a specific tool, and an orchestrator that
        # does not know telemetry_available yet has to take the total-minus-used
        # path rather than trust this as an nvidia-smi reading.
        assert snapshot.nvidia_smi_available is False
        assert snapshot.telemetry_available is True
        assert len(snapshot.devices) == 1
        device = snapshot.devices[0]
        assert device.kind == "metal"
        assert device.name == "Apple M3 Pro"
        assert device.extra["unified_memory"] is True
        assert device.extra["max_buffer_length_mb"] == pytest.approx(22613000192 / 1024**2)
        assert snapshot.free_memory_mb == pytest.approx(snapshot.total_memory_mb - snapshot.used_memory_mb, abs=0.1)

    @pytest.mark.asyncio
    async def test_used_memory_tracks_wired_pages(self) -> None:
        collector = metal.MetalMetricsCollector(poll_interval=3600)
        with (
            patch.object(metal, "probe_device_info", return_value=self.DEVICE_INFO),
            patch.object(metal, "read_vm_stat", return_value=metal.parse_vm_stat(VM_STAT_SAMPLE)),
        ):
            await collector.start()
            snapshot = await collector.get_snapshot()
            await collector.stop()
        assert snapshot.used_memory_mb == pytest.approx(218557 * PAGE / 1024**2, abs=1)

    @pytest.mark.asyncio
    async def test_falls_back_to_sysctl_when_mlx_is_unreachable(self) -> None:
        collector = metal.MetalMetricsCollector(poll_interval=3600)
        with (
            patch.object(metal, "probe_device_info", return_value=None),
            patch.object(metal, "_sysctl_int", lambda name: {"hw.memsize": 38654705664}.get(name, 0)),
            patch.object(metal, "read_vm_stat", return_value=metal.parse_vm_stat(VM_STAT_SAMPLE)),
        ):
            await collector.start()
            snapshot = await collector.get_snapshot()
            await collector.stop()

        assert collector.available is True
        # Degraded, and it must say so — the estimate is not authoritative.
        assert "estimated" in snapshot.degraded_reason
        assert snapshot.total_memory_mb == pytest.approx(38654705664 * metal._DEFAULT_WIRED_FRACTION / 1024**2, abs=1)
        # The estimate is not measured telemetry: consumers that gate on the
        # flag keep their registration-time / total-minus-used values until a
        # real mlx probe succeeds, instead of scheduling against one
        # machine's measured constant.
        assert snapshot.telemetry_available is False

    @pytest.mark.asyncio
    async def test_honours_an_explicit_wired_limit(self) -> None:
        """iogpu.wired_limit_mb is authoritative when an operator set it."""
        collector = metal.MetalMetricsCollector(poll_interval=3600)
        with (
            patch.object(metal, "probe_device_info", return_value=None),
            patch.object(
                metal,
                "_sysctl_int",
                lambda name: {"hw.memsize": 38654705664, "iogpu.wired_limit_mb": 32768}.get(name, 0),
            ),
            patch.object(metal, "read_vm_stat", return_value=metal.parse_vm_stat(VM_STAT_SAMPLE)),
        ):
            await collector.start()
            snapshot = await collector.get_snapshot()
            await collector.stop()
        assert snapshot.total_memory_mb == pytest.approx(32768, abs=1)

    @pytest.mark.asyncio
    async def test_disables_itself_when_nothing_can_be_read(self) -> None:
        collector = metal.MetalMetricsCollector(poll_interval=3600)
        with (
            patch.object(metal, "probe_device_info", return_value=None),
            patch.object(metal, "_sysctl_int", lambda name: None),
        ):
            await collector.start()
            snapshot = await collector.get_snapshot()

        assert collector.available is False
        assert collector.device_count == 0
        assert collector.per_gpu_vram_mb == 0.0
        assert snapshot.mode == "none"
        assert snapshot.telemetry_available is False

    @pytest.mark.asyncio
    async def test_exposes_the_gpu_collector_interface(self) -> None:
        """LaneManager duck-types on these; a rename would break it silently."""
        collector = metal.MetalMetricsCollector(poll_interval=3600)
        with (
            patch.object(metal, "probe_device_info", return_value=self.DEVICE_INFO),
            patch.object(metal, "read_vm_stat", return_value=metal.parse_vm_stat(VM_STAT_SAMPLE)),
        ):
            await collector.start()
            assert collector.available is True
            assert collector.device_count == 1
            assert collector.per_gpu_vram_mb == pytest.approx(30150672384 / 1024**2, abs=1)
            await collector.force_poll()
            await collector.stop()


class TestRunHelper:
    def test_returns_none_when_the_binary_is_missing(self) -> None:
        assert metal._run(["definitely-not-a-real-binary-xyz"]) is None

    def test_returns_none_on_nonzero_exit(self) -> None:
        with patch.object(subprocess, "run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = "ignored"
            assert metal._run(["false"]) is None

    def test_returns_none_on_timeout(self) -> None:
        with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 1)):
            assert metal._run(["sleep", "99"]) is None
