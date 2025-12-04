# Database Migrations

This directory contains SQL migration scripts for upgrading the Logos database schema from the `main` branch to the `logos/scheduling-data-interface` branch.

## Migration Scripts

| Script | Description | Tables/Columns Modified |
|--------|-------------|------------------------|
| `001_add_provider_ssh_columns.sql` | Add SSH connectivity for private Ollama servers | providers: ssh_host, ssh_user, ssh_port, ssh_key_path, ssh_remote_ollama_port |
| `002_add_provider_sdi_columns.sql` | Add SDI monitoring and configuration columns | providers: provider_type, ollama_admin_url, total_vram_mb, parallel_capacity, keep_alive_seconds, max_loaded_models, updated_at |
| `003_create_model_provider_config.sql` | Create per-model per-provider config table | NEW TABLE: model_provider_config |
| `004_add_log_entry_sdi_columns.sql` | Add SDI metrics to log entries | log_entry: priority, queue_depth_at_arrival, utilization_at_arrival, queue_wait_ms, was_cold_start, load_duration_ms |
| `005_create_request_events_table.sql` | Create request monitoring table | NEW TABLE: request_events, NEW TYPE: result_status_enum |

## Running Migrations

### Option 1: Apply All Migrations (Recommended)

Run all migrations in order:

```bash
# From repository root
cd db/migrations

# Run each migration in order
docker exec -i logos-db psql -U postgres -d logosdb < 001_add_provider_ssh_columns.sql
docker exec -i logos-db psql -U postgres -d logosdb < 002_add_provider_sdi_columns.sql
docker exec -i logos-db psql -U postgres -d logosdb < 003_create_model_provider_config.sql
docker exec -i logos-db psql -U postgres -d logosdb < 004_add_log_entry_sdi_columns.sql
docker exec -i logos-db psql -U postgres -d logosdb < 005_create_request_events_table.sql
```

Or use the convenience script:
```bash
./run_all_migrations.sh
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
- **Idempotent**: Safe to run multiple times
- **Non-destructive**: Only add columns/tables, never drop existing data
- **Backward compatible**: Existing queries continue to work

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
