-- Migration 030: Document the `logos_peer` provider type.
--
-- The `providers.provider_type` column is `VARCHAR(20)`, which already accommodates
-- the value `logos_peer`, so no DDL is required. This migration only refreshes the
-- column comment so operators inspecting the schema see `logos_peer` listed.

COMMENT ON COLUMN providers.provider_type IS
    'Provider kind: cloud | azure | logosnode | logos_peer';
