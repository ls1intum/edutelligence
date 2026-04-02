from logos.monitoring.recorder import MonitoringRecorder


def test_recorder_updates_log_entry_metrics_by_request_id():
    calls = []

    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update_request_log_metrics(self, **kwargs):
            calls.append(kwargs)

    recorder = MonitoringRecorder(db_factory=lambda: DummyDB())

    recorder.record_enqueue(
        request_id="req-1",
        model_id=27,
        provider_id=12,
        initial_priority="normal",
        queue_depth=3,
        timeout_s=60,
    )
    recorder.record_scheduled(
        request_id="req-1",
        model_id=27,
        provider_id=12,
        priority_when_scheduled="normal",
        queue_depth_at_schedule=1,
        provider_metrics={"available_vram_mb": 1024},
    )
    recorder.record_complete(
        request_id="req-1",
        result_status="success",
        cold_start=False,
    )

    assert calls[0]["request_id"] == "req-1"
    assert calls[0]["initial_priority"] == "normal"
    assert calls[0]["queue_depth_at_enqueue"] == 3
    assert calls[0]["timeout_s"] == 60

    assert calls[1]["priority_when_scheduled"] == "normal"
    assert calls[1]["queue_depth_at_schedule"] == 1
    assert calls[1]["available_vram_mb"] == 1024

    assert calls[2]["result_status"] == "success"
    assert calls[2]["cold_start"] is False
