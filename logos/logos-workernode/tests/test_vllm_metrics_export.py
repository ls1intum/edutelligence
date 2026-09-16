from __future__ import annotations

import httpx
import pytest

from logos_worker_node.lane_manager import LaneManager
from logos_worker_node.models import LaneConfig, ProcessState, ProcessStatus, WorkerConfig
from logos_worker_node.vllm_metrics_export import collect_vllm_metrics_text
from logos_worker_node.vllm_metrics_merge import merge_metric_families

_TEXT_A = """# HELP vllm:num_requests_running Number of requests currently running
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{model_name="foo"} 3.0
"""

_TEXT_B = """# HELP vllm:num_requests_running Number of requests currently running
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{model_name="foo"} 5.0
"""


def test_merge_metric_families_relabels_and_dedupes_by_name() -> None:
    families = merge_metric_families(
        [
            ({"lane_id": "lane-a"}, _TEXT_A),
            ({"lane_id": "lane-b"}, _TEXT_B),
        ]
    )

    assert [f.name for f in families] == ["vllm:num_requests_running"]
    family = families[0]
    assert len(family.samples) == 2
    by_lane = {s.labels["lane_id"]: s for s in family.samples}
    assert by_lane["lane-a"].value == 3.0
    assert by_lane["lane-b"].value == 5.0
    # The original vLLM label survives alongside the injected one.
    assert by_lane["lane-a"].labels["model_name"] == "foo"


def test_merge_metric_families_skips_empty_and_unparseable_sources() -> None:
    families = merge_metric_families(
        [
            ({"lane_id": "lane-a"}, ""),
            ({"lane_id": "lane-b"}, "not a valid exposition line {{{"),
            ({"lane_id": "lane-c"}, _TEXT_A),
        ]
    )

    assert [f.name for f in families] == ["vllm:num_requests_running"]
    assert len(families[0].samples) == 1
    assert families[0].samples[0].labels["lane_id"] == "lane-c"


@pytest.mark.asyncio
async def test_collect_vllm_metrics_text_skips_failed_lane(monkeypatch) -> None:
    class _Resp:
        def __init__(self, status_code: int, text: str) -> None:
            self.status_code = status_code
            self.text = text

    class _HttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
            return None

        async def get(self, url, timeout=None):  # noqa: ARG002
            if ":15001" in url:
                return _Resp(200, _TEXT_A)
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(
        "logos_worker_node.vllm_metrics_export.httpx.AsyncClient",
        lambda: _HttpClient(),
    )

    text = await collect_vllm_metrics_text(
        [
            ("lane-good", "foo-model", 15001),
            ("lane-dead", "foo-model", 15002),
        ]
    )

    assert 'lane_id="lane-good"' in text
    assert 'lane_id="lane-dead"' not in text
    assert 'model="foo-model"' in text


@pytest.mark.asyncio
async def test_collect_vllm_metrics_text_empty_without_endpoints() -> None:
    assert await collect_vllm_metrics_text([]) == ""


def test_running_vllm_endpoints_filters_by_process_state() -> None:
    manager = LaneManager(WorkerConfig(), lane_port_start=15001, lane_port_end=15010)

    class FakeHandle:
        def __init__(self, lane_id: str, port: int, state: ProcessState, model: str) -> None:
            self.lane_id = lane_id
            self.port = port
            self.lane_config = LaneConfig(model=model)
            self._state = state

        def status(self) -> ProcessStatus:
            return ProcessStatus(state=self._state, pid=1)

    manager._handles["lane-running"] = FakeHandle(  # noqa: SLF001
        "lane-running", 15001, ProcessState.RUNNING, "model-a"
    )
    manager._handles["lane-stopped"] = FakeHandle(  # noqa: SLF001
        "lane-stopped", 15002, ProcessState.STOPPED, "model-b"
    )

    assert manager.running_vllm_endpoints() == [("lane-running", "model-a", 15001)]
