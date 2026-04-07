import sys
import types
from datetime import datetime, timezone

matplotlib_stub = types.ModuleType("matplotlib")
matplotlib_stub.use = lambda *args, **kwargs: None
pyplot_stub = types.ModuleType("matplotlib.pyplot")
ticker_stub = types.ModuleType("matplotlib.ticker")
ticker_stub.MaxNLocator = object
ticker_stub.ScalarFormatter = object
sys.modules["matplotlib"] = matplotlib_stub
sys.modules["matplotlib.pyplot"] = pyplot_stub
sys.modules["matplotlib.ticker"] = ticker_stub

from tests.performance.run_api_workload import (
    LogRecord,
    RequestResult,
    WorkloadEntry,
    build_rows,
    is_local_api_base,
    parse_streaming_response,
)


def _entry(request_id: str) -> WorkloadEntry:
    return WorkloadEntry(
        request_id=request_id,
        arrival_offset=0.0,
        mode="interactive",
        priority="mid",
        body_json='{"messages":[{"role":"user","content":"hi"}]}',
    )


def _log(request_id: str, model_name: str) -> LogRecord:
    request_ts = datetime(2026, 3, 22, 10, 0, 0, tzinfo=timezone.utc)
    response_ts = datetime(2026, 3, 22, 10, 0, 2, tzinfo=timezone.utc)
    return LogRecord(
        log_id=1,
        request_id=request_id,
        request_ts=request_ts,
        ttft_ts=datetime(2026, 3, 22, 10, 0, 0, 500000, tzinfo=timezone.utc),
        response_ts=response_ts,
        provider_id=None,
        provider_name="azure",
        model_id=None,
        model_name=model_name,
        response_payload={"usage": {"completion_tokens": 5}},
        enqueue_ts=request_ts,
        scheduled_ts=datetime(2026, 3, 22, 10, 0, 1, tzinfo=timezone.utc),
        complete_ts=response_ts,
        result_status="success",
    )


def test_build_rows_uses_server_request_id_mapping_for_out_of_order_logs():
    results = [
        RequestResult(_entry("csv-1"), 200, {"ok": True}, None, 100.0, server_request_id="srv-2"),
        RequestResult(_entry("csv-2"), 200, {"ok": True}, None, 100.0, server_request_id="srv-1"),
    ]
    logs = {
        "srv-1": _log("srv-1", "model-a"),
        "srv-2": _log("srv-2", "model-b"),
    }

    _, detail_records, missing_logs = build_rows(results, logs, latency_slo_ms=10_000.0)

    assert missing_logs == 0
    assert detail_records[0]["request_id"] == "csv-1"
    assert detail_records[0]["server_request_id"] == "srv-2"
    assert detail_records[0]["model_name"] == "model-b"
    assert detail_records[0]["request_body_json"] == '{"messages":[{"role":"user","content":"hi"}]}'
    assert detail_records[0]["response_body_json"] == '{"usage": {"completion_tokens": 5}}'
    assert detail_records[0]["completion_tokens"] == 5
    assert detail_records[0]["total_tokens"] is None
    assert detail_records[1]["request_id"] == "csv-2"
    assert detail_records[1]["server_request_id"] == "srv-1"
    assert detail_records[1]["model_name"] == "model-a"


def test_build_rows_marks_missing_header_and_missing_log():
    results = [
        RequestResult(_entry("csv-no-header"), 200, {"ok": True}, None, 100.0, server_request_id=None),
        RequestResult(_entry("csv-missing-log"), 200, {"ok": True}, None, 100.0, server_request_id="srv-missing"),
    ]

    _, detail_records, missing_logs = build_rows(results, {}, latency_slo_ms=10_000.0)

    assert missing_logs == 2
    assert "missing_request_id_header" in detail_records[0]["error"]
    assert "log entry missing" in detail_records[1]["error"]


def test_is_local_api_base_matches_current_local_hosts():
    assert is_local_api_base("http://localhost:8080")
    assert is_local_api_base("https://127.0.0.1:8443")
    assert not is_local_api_base("https://logos.example.com")


def test_render_payload_preserves_body_json_without_injecting_runner_metadata():
    entry = WorkloadEntry(
        request_id="csv-1",
        arrival_offset=0.0,
        mode="interactive",
        priority="high",
        body_json='{"model":"azure-gpt-4-omni","messages":[{"role":"user","content":"hi"}]}',
    )

    assert entry.render_payload() == {
        "model": "azure-gpt-4-omni",
        "messages": [{"role": "user", "content": "hi"}],
    }


def test_parse_streaming_response_reconstructs_message_and_usage():
    raw = "\n".join([
        'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"hel"}}]}',
        'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"lo"}}]}',
        'data: {"id":"chatcmpl-1","choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}',
        "data: [DONE]",
    ])

    parsed = parse_streaming_response(raw)

    assert parsed["choices"][0]["message"]["content"] == "hello"
    assert parsed["usage"] == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
