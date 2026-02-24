-- Migration: Add pg_cron retention policy for ollama_provider_snapshots
-- Deletes snapshots older than 7 days, runs every 6 hours

CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Remove existing job if present (idempotent)
SELECT cron.unschedule('cleanup-old-snapshots')
WHERE EXISTS (
    SELECT 1 FROM cron.job WHERE jobname = 'cleanup-old-snapshots'
);

-- Schedule cleanup: every 6 hours, delete rows older than 7 days
SELECT cron.schedule(
    'cleanup-old-snapshots',
    '0 */6 * * *',
    $$DELETE FROM ollama_provider_snapshots WHERE snapshot_ts < NOW() - INTERVAL '7 days'$$
);
