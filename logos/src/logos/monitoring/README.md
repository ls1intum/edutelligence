# Request Monitoring

Lightweight, on-device monitoring writes request lifecycle/performance fields onto the
existing `log_entry` row, keyed by `request_id`.
`SchedulingManager` emits `enqueue` and `scheduled` automatically when a `MonitoringRecorder`
is provided (and uses `scheduled_ts` as the start marker).

## Schema (db/init.sql)
- Correlation: `request_id`
- Context: `model_id`, `provider_id`, `initial_priority`, `priority_when_scheduled`, `timeout_s`
- Queue: `queue_depth_at_enqueue`, `queue_depth_at_schedule`, `queue_wait_ms`
- Timestamps: `timestamp_request`, `timestamp_forwarding`, `timestamp_response`
- Snapshots: `available_vram_mb`, `azure_rate_remaining_requests`, `azure_rate_remaining_tokens`
- Outcome: `was_cold_start`, `result_status` (`success` | `error` | `timeout`), `error_message`

## Recorder API (src/logos/monitoring/recorder.py)
- `record_enqueue(request_id, model_id, provider_id, initial_priority, queue_depth, timeout_s=None)`
- `record_scheduled(request_id, model_id, provider_id, priority_when_scheduled, queue_depth_at_schedule, provider_metrics=None)`
- `record_complete(request_id, result_status, cold_start=None, error_message=None)`

Usage:
```python
from logos.monitoring.recorder import MonitoringRecorder
from logos.pipeline.utilization_scheduler import UtilizationAwareScheduler
from logos.pipeline.pipeline import RequestPipeline

recorder = MonitoringRecorder()
scheduler = UtilizationAwareScheduler(queue_manager, ollama_facade, azure_facade, model_registry)
pipeline = RequestPipeline(classifier, scheduler, executor, context_resolver, recorder)
```

## Notes
- Queue wait = `timestamp_forwarding - timestamp_request`; duration = `timestamp_response - timestamp_forwarding`.
- The legacy `request_events` table has been retired. Runtime writes land on `log_entry`.
