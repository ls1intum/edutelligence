-- Migration 031: Optional priority cap per process.
--
-- Lets a Logos upstream pin a peer's traffic to a maximum priority level. Use
-- case: a prod Logos serves both its own local traffic and forwarded traffic
-- from a dev peer; the dev peer's process row gets `peer_priority = 'low'`
-- so prod local traffic preempts it on the shared priority queue. NULL = no
-- cap (default for non-peer processes and for peers that should run
-- unrestricted).

ALTER TABLE process
    ADD COLUMN IF NOT EXISTS peer_priority VARCHAR(10);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'process_peer_priority_check'
    ) THEN
        ALTER TABLE process
            ADD CONSTRAINT process_peer_priority_check
            CHECK (peer_priority IS NULL OR peer_priority IN ('low', 'normal', 'high'));
    END IF;
END$$;

COMMENT ON COLUMN process.peer_priority IS
    'Optional priority cap for requests authenticated by this process. one of low | normal | high. NULL = uncapped.';

INSERT INTO schema_migrations (filename)
VALUES ('031_add_peer_priority_to_process.sql')
ON CONFLICT (filename) DO NOTHING;
