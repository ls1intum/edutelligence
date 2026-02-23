-- Migration: Drop model_provider_config table (deprecated)
-- Safe to run multiple times.

DROP TABLE IF EXISTS model_provider_config CASCADE;
