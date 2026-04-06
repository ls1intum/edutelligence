from pathlib import Path
from datetime import datetime, timezone

from tests.performance.run_api_workload import (
    LogRecord,
    RequestResult,
    WorkloadEntry,
    build_per_model_summary_rows,
    build_request_response_records,
    build_rows,
    infer_workload_scenario_manifest,
    is_local_api_base,
    parse_streaming_response,
    resolve_output_layout,
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


def test_build_rows_adds_scenario_and_timestamp_fields():
    results = [RequestResult(_entry("csv-1"), 200, {"ok": True}, None, 100.0, server_request_id="srv-1")]
    logs = {"srv-1": _log("srv-1", "model-a")}

    _, detail_records, _ = build_rows(results, logs, latency_slo_ms=10_000.0, scenario_name="scenario-alpha")

    record = detail_records[0]
    assert record["scenario_name"] == "scenario-alpha"
    assert record["arrival_offset_ms"] == 0.0
    assert record["request_ts_utc"] == "2026-03-22T10:00:00+00:00"
    assert record["ttft_ts_utc"] == "2026-03-22T10:00:00.500000+00:00"
    assert record["response_ts_utc"] == "2026-03-22T10:00:02+00:00"


def test_build_rows_marks_missing_header_and_missing_log():
    results = [
        RequestResult(_entry("csv-no-header"), 200, {"ok": True}, None, 100.0, server_request_id=None),
        RequestResult(_entry("csv-missing-log"), 200, {"ok": True}, None, 100.0, server_request_id="srv-missing"),
    ]

    _, detail_records, missing_logs = build_rows(results, {}, latency_slo_ms=10_000.0)

    assert missing_logs == 2
    assert "missing_request_id_header" in detail_records[0]["error"]
    assert "log entry missing" in detail_records[1]["error"]


def test_build_request_response_records_keep_full_payloads():
    large_text = "x" * 3000
    results = [
        RequestResult(
            _entry("csv-1"),
            200,
            {"choices": [{"message": {"content": large_text}}]},
            None,
            100.0,
            server_request_id="srv-1",
        )
    ]
    log = _log("srv-1", "model-a")
    log.response_payload = {"choices": [{"message": {"content": large_text}}], "usage": {"completion_tokens": 5}}
    _, detail_records, _ = build_rows(results, {"srv-1": log}, latency_slo_ms=10_000.0, scenario_name="scenario-alpha")

    records = build_request_response_records(detail_records)

    assert len(detail_records[0]["response_body_json"]) == 2000
    assert records[0]["response_payload"]["choices"][0]["message"]["content"] == large_text
    assert records[0]["request_payload"] == {"messages": [{"role": "user", "content": "hi"}]}


def test_build_per_model_summary_rows_aggregates_metrics():
    results = [
        RequestResult(_entry("csv-1"), 200, {"ok": True}, None, 100.0, server_request_id="srv-1"),
        RequestResult(_entry("csv-2"), 200, {"ok": True}, None, 100.0, server_request_id="srv-2"),
    ]
    log_a = _log("srv-1", "model-a")
    log_b = _log("srv-2", "model-a")
    log_b.ttft_ts = datetime(2026, 3, 22, 10, 0, 1, tzinfo=timezone.utc)
    log_b.response_ts = datetime(2026, 3, 22, 10, 0, 4, tzinfo=timezone.utc)
    log_b.complete_ts = log_b.response_ts
    _, detail_records, _ = build_rows(results, {"srv-1": log_a, "srv-2": log_b}, latency_slo_ms=10_000.0)

    rows = build_per_model_summary_rows(detail_records)

    assert rows == [
        {
            "model_name": "model-a",
            "request_count": 2,
            "successful_requests": 2,
            "success_rate_pct": 100.0,
            "p50_ttft_ms": 750.0,
            "p95_ttft_ms": 975.0,
            "p99_ttft_ms": 995.0,
            "p50_latency_ms": 3000.0,
            "p95_latency_ms": 3900.0,
            "p99_latency_ms": 3980.0,
            "p50_queue_wait_ms": 1000.0,
            "p95_queue_wait_ms": 1000.0,
            "p99_queue_wait_ms": 1000.0,
            "p50_processing_ms": 2000.0,
            "p95_processing_ms": 2900.0,
            "p99_processing_ms": 2980.0,
        }
    ]


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


def test_infer_workload_scenario_manifest_counts_models():
    entries = [
        WorkloadEntry(
            request_id="req-1",
            arrival_offset=10.0,
            mode="interactive",
            priority="mid",
            body_json='{"model":"model-a","messages":[{"role":"user","content":"hi"}]}',
        ),
        WorkloadEntry(
            request_id="req-2",
            arrival_offset=20.0,
            mode="interactive",
            priority="mid",
            body_json='{"model":"model-b","messages":[{"role":"user","content":"hi"}]}',
        ),
        WorkloadEntry(
            request_id="req-3",
            arrival_offset=30.0,
            mode="interactive",
            priority="mid",
            body_json='{"model":"model-a","messages":[{"role":"user","content":"hi"}]}',
        ),
    ]

    manifest = infer_workload_scenario_manifest(Path("sample.csv"), entries)

    assert manifest["scenario_name"] == "sample"
    assert manifest["model_counts"] == {"model-a": 2, "model-b": 1}
    assert manifest["total_requests"] == 3
    assert manifest["duration_ms"] == 31


def test_resolve_output_layout_includes_new_artifacts(tmp_path):
    layout = resolve_output_layout(tmp_path / "my_run.csv", Path("tests/performance/workloads/explicit/10m/sample.csv"), "20260406_120000")

    assert layout.scenario_manifest_path.name == "scenario_manifest.json"
    assert layout.request_response_path.name == "request_response.jsonl"
    assert layout.per_model_summary_path.name == "per_model_summary.csv"
    assert layout.latency_distribution_csv_path.name == "latency_distribution.csv"
    assert layout.ttft_distribution_csv_path.name == "ttft_distribution.csv"
