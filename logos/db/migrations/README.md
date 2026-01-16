# Database Migrations

This directory contains SQL migration scripts for upgrading the Logos database schema from the `main` branch to the `logos/scheduling-data-interface` branch.

## Migration Scripts

| Script | Description | Tables/Columns Modified |
|--------|-------------|------------------------|
| `001_add_jobs_table.sql` | Add jobs table for async job tracking | NEW TABLE: jobs, NEW TYPE: job_status_enum |
| `002_add_provider_sdi_columns.sql` | Add SDI columns to providers | providers: provider_type, ollama_admin_url, total_vram_mb, parallel_capacity, keep_alive_seconds, max_loaded_models, updated_at |
| `003a_drop_provider_ssh_columns.sql` | Remove SSH connectivity columns from providers | providers: DROP ssh_host, ssh_user, ssh_port, ssh_key_path, ssh_remote_ollama_port |
| `003b_create_model_provider_config.sql` | Create per-model per-provider config table | NEW TABLE: model_provider_config |
| `004_add_log_entry_sdi_columns.sql` | Add SDI metrics to log entries | log_entry: priority, queue_depth_at_arrival, utilization_at_arrival, queue_wait_ms, was_cold_start, load_duration_ms |
| `005_create_request_events_table.sql` | Create request monitoring table | NEW TABLE: request_events, NEW TYPE: result_status_enum |
| `006_update_model_endpoints_to_local_ollama.sql` | Point TUM GPU endpoints to local Ollama | models: UPDATE endpoint for TUM GPU models |
| `007_rename_openwebui_to_ollama_no_auth.sql` | Rename openwebui provider to ollama and clear auth | providers: UPDATE name, auth_name, auth_format |
| `008_create_ollama_provider_snapshots.sql` | Create Ollama provider monitoring table | NEW TABLE: ollama_provider_snapshots |

## Running Migrations

### Option 1: Apply All Migrations (Recommended)

Run all migrations in order:

```bash
# From repository root
cd db/migrations

# Use the convenience script (recommended):
./run_all_migrations.sh
```

Or run each migration individually in order:
```bash
docker exec -i logos-db psql -U postgres -d logosdb < 001_add_jobs_table.sql
docker exec -i logos-db psql -U postgres -d logosdb < 002_add_provider_sdi_columns.sql
docker exec -i logos-db psql -U postgres -d logosdb < 003a_drop_provider_ssh_columns.sql
docker exec -i logos-db psql -U postgres -d logosdb < 003b_create_model_provider_config.sql
docker exec -i logos-db psql -U postgres -d logosdb < 004_add_log_entry_sdi_columns.sql
docker exec -i logos-db psql -U postgres -d logosdb < 005_create_request_events_table.sql
docker exec -i logos-db psql -U postgres -d logosdb < 006_update_model_endpoints_to_local_ollama.sql
docker exec -i logos-db psql -U postgres -d logosdb < 007_rename_openwebui_to_ollama_no_auth.sql
docker exec -i logos-db psql -U postgres -d logosdb < 008_create_ollama_provider_snapshots.sql
```

### Option 2: Apply Specific Migration

```bash
docker exec -i logos-db psql -U postgres -d logosdb < 00X_migration_name.sql
```

### Option 3: Fresh Database Install

For new installations, use `db/init.sql` which already includes all changes:

```bash
docker exec -i logos-db psql -U postgres -d logosdb < db/init.sql
```

## Safety Features

All migration scripts are designed to be:
- **Idempotent**: Safe to run multiple times without errors
- **Atomic**: Each migration uses IF EXISTS/IF NOT EXISTS checks to prevent conflicts
- **Safe**: Use ADD COLUMN IF NOT EXISTS and CREATE TABLE IF NOT EXISTS patterns
- **Minimal impact**: Most migrations only add new columns/tables; the only destructive migration (003a) removes unused SSH columns

## Verification

After running migrations, verify the schema:

```bash
# Check providers table structure
docker exec logos-db psql -U postgres -d logosdb -c "\d providers"

# Check new tables exist
docker exec logos-db psql -U postgres -d logosdb -c "\dt"

# Verify enum types
docker exec logos-db psql -U postgres -d logosdb -c "\dT+"
```
