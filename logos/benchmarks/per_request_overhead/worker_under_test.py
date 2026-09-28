"""Worker-under-test process for the per-request overhead benchmark.

Runs the REAL worker components — ``LaneManager`` + ``LogosBridgeClient`` —
with a single warm ``FakeLaneHandle`` pointing at the mock lane. There is no
uvicorn and no real lane process: the bridge dials out to the orchestrator
(shared-key auth + WebSocket, hello, status pushes, command loop) exactly
like in production, and every command the orchestrator sends (``infer``)
flows through the real relay path into the mock lane.

Environment (set by run_benchmark.py):
  LOGOS_BENCH_ORCHESTRATOR_URL   e.g. http://127.0.0.1:8090
  LOGOS_BENCH_LANE_PORT          mock lane port (the fake lane's port)
  LOGOS_BENCH_MODEL              model name (default bench-local-model)
  LOGOS_BENCH_SHARED_KEY         workers' shared_key (providers.api_key)
  LOGOS_WORKER_PERF_TRACE        "1" → perf dict in command_result
  LOGOS_STATE_DIR                state dir (tmp) for profile persistence

Exit on SIGTERM/SIGINT after a clean bridge shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from types import SimpleNamespace

# The worker package is not installed into the venv (CI installs only the
# orchestrator package); make it importable from the repo checkout before the
# logos_worker_node imports below.
_WORKER_PKG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logos-workernode"
)
if _WORKER_PKG not in sys.path:
    sys.path.insert(0, _WORKER_PKG)

from logos_worker_node.gpu import GpuMetricsCollector  # noqa: E402
from logos_worker_node.lane_manager import LaneManager  # noqa: E402
from logos_worker_node.logos_bridge import LogosBridgeClient  # noqa: E402
from logos_worker_node.models import AppConfig, LaneConfig, LogosConfig, VllmConfig, WorkerConfig  # noqa: E402


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


async def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOGOS_BENCH_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    log = logging.getLogger("worker-under-test")

    orchestrator_url = _env("LOGOS_BENCH_ORCHESTRATOR_URL")
    lane_port = int(_env("LOGOS_BENCH_LANE_PORT", "11436"))
    model = _env("LOGOS_BENCH_MODEL", "bench-local-model")
    shared_key = _env("LOGOS_BENCH_SHARED_KEY", "lg-worker-shared-0000")
    if not orchestrator_url or not shared_key:
        log.error("LOGOS_BENCH_ORCHESTRATOR_URL / LOGOS_BENCH_SHARED_KEY required")
        return 2

    config = AppConfig(
        worker=WorkerConfig(
            name="bench-worker",
            gpu_devices="none",
            lane_port_start=lane_port,
            lane_port_end=lane_port,
            max_lanes=1,
        ),
        logos=LogosConfig(
            enabled=True,
            logos_url=orchestrator_url,
            shared_key=shared_key,
            allow_insecure_http=True,
            capabilities_models=[model],
        ),
    )

    gpu_collector = GpuMetricsCollector(poll_interval=5)
    await gpu_collector.start()  # no-op without nvidia-smi (degraded mode)

    lane_manager = LaneManager(
        config.worker,
        vllm_engine_config=config.engines.vllm,
        lane_port_start=lane_port,
        lane_port_end=lane_port,
        nvidia_smi_available=lambda: False,
        gpu_snapshot=gpu_collector.get_snapshot,
        gpu_force_poll=gpu_collector.force_poll,
    )

    from fake_lane_handle import FakeLaneHandle  # noqa: PLC0415 (sys.path set above)

    lane_id = model
    lane_config = LaneConfig(model=model, vllm=True, vllm_config=VllmConfig(enable_sleep_mode=True))
    handle = FakeLaneHandle(lane_id=lane_id, port=lane_port, lane_config=lane_config)
    lane_manager._handles[lane_id] = handle  # noqa: SLF001 (benchmark injection, same pattern as worker unit tests)

    # The bridge reads app.state.{config, lane_manager, gpu_collector, logos_bridge}
    # (build_runtime_status) — a plain namespace object is enough.
    bridge = LogosBridgeClient(None, config.logos)
    app = SimpleNamespace(
        state=SimpleNamespace(
            config=config,
            lane_manager=lane_manager,
            gpu_collector=gpu_collector,
            logos_bridge=bridge,
        )
    )
    bridge._app = app  # noqa: SLF001 (the client only ever touches app.state)

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # pragma: no cover (non-POSIX)
            pass

    await bridge.start()
    log.info("worker-under-test up: lane '%s' → mock lane :%d, orchestrator %s", lane_id, lane_port, orchestrator_url)

    # Wait for the bridge to report a successful connection (or until stopped).
    connected_logged = False
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
            break
        except asyncio.TimeoutError:
            pass
        if bridge.transport_status().connected and not connected_logged:
            connected_logged = True
            log.info("bridge connected (worker_id=%s)", bridge.worker_id)

    await bridge.stop()
    await gpu_collector.stop()
    log.info("worker-under-test stopped cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
