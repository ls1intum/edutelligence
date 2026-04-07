-- Migration: remove the legacy request_events table after collapsing metrics onto log_entry

DROP TABLE IF EXISTS request_events;
