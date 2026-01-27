# Request Monitoring

Lightweight, on-device monitoring writes one row per `request_id` into `request_events`.
`SchedulingManager` emits `enqueue` and `scheduled` automatically when a `MonitoringRecorder`
is provided (and uses `scheduled_ts` as the start marker).

## Schema (db/init.sql)
- `request_id` (pk)
- Context: `model_id`, `provider_id`, `initial_priority`, `priority_when_scheduled`, `timeout_s`
- Queue: `queue_depth_at_enqueue`, `queue_depth_at_schedule`
- Timestamps: `enqueue_ts`, `scheduled_ts`, `request_complete_ts`
- Snapshots: `available_vram_mb`, `azure_rate_remaining_requests`, `azure_rate_remaining_tokens`
- Outcome: `cold_start`, `result_status` (`success` | `error` | `timeout`), `error_message`

## Recorder API (src/logos/monitoring/recorder.py)
- `record_enqueue(request_id, model_id, provider_id, initial_priority, queue_depth, timeout_s=None)`
- `record_scheduled(request_id, model_id, provider_id, priority_when_scheduled, queue_depth_at_schedule, available_vram_mb=None, azure_rate_remaining_requests=None, azure_rate_remaining_tokens=None)`
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
- Queue wait = `scheduled_ts - enqueue_ts`; duration = `request_complete_ts - scheduled_ts`.
- TODO: if a future scheduler reassigns requests between models mid-queue, capture the reassignment time and new queue depth before updating the row. Current implementation assumes a fixed model per enqueue.
