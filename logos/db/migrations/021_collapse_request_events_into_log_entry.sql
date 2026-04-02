-- Migration: consolidate scheduler/performance metrics onto log_entry

ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS initial_priority TEXT;

ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS priority_when_scheduled TEXT;

ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS queue_depth_at_enqueue INTEGER;

ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS queue_depth_at_schedule INTEGER;

ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS timeout_s INTEGER;

ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS available_vram_mb INTEGER;

ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS azure_rate_remaining_requests INTEGER;

ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS azure_rate_remaining_tokens INTEGER;

ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS result_status result_status_enum;

ALTER TABLE log_entry
    ADD COLUMN IF NOT EXISTS error_message TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_log_entry_request_id_unique
    ON log_entry(request_id)
    WHERE request_id IS NOT NULL;

UPDATE log_entry le
SET
    initial_priority = COALESCE(le.initial_priority, re.initial_priority),
    priority_when_scheduled = COALESCE(le.priority_when_scheduled, re.priority_when_scheduled),
    queue_depth_at_enqueue = COALESCE(le.queue_depth_at_enqueue, re.queue_depth_at_enqueue),
    queue_depth_at_schedule = COALESCE(le.queue_depth_at_schedule, re.queue_depth_at_schedule),
    timeout_s = COALESCE(le.timeout_s, re.timeout_s),
    timestamp_forwarding = COALESCE(le.timestamp_forwarding, re.scheduled_ts),
    timestamp_response = COALESCE(le.timestamp_response, re.request_complete_ts),
    available_vram_mb = COALESCE(le.available_vram_mb, re.available_vram_mb),
    azure_rate_remaining_requests = COALESCE(
        le.azure_rate_remaining_requests,
        re.azure_rate_remaining_requests
    ),
    azure_rate_remaining_tokens = COALESCE(
        le.azure_rate_remaining_tokens,
        re.azure_rate_remaining_tokens
    ),
    was_cold_start = COALESCE(le.was_cold_start, re.cold_start),
    result_status = COALESCE(le.result_status, re.result_status),
    error_message = COALESCE(le.error_message, re.error_message),
    queue_wait_ms = COALESCE(
        le.queue_wait_ms,
        CASE
            WHEN re.enqueue_ts IS NOT NULL AND re.scheduled_ts IS NOT NULL
                THEN EXTRACT(EPOCH FROM (re.scheduled_ts - re.enqueue_ts)) * 1000
            ELSE NULL
        END
    )
FROM request_events re
WHERE le.request_id IS NOT NULL
  AND le.request_id = re.request_id;
