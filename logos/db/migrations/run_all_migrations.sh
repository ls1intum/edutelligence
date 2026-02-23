#!/usr/bin/env bash
# Apply all database migrations in order
# Safe to run multiple times - migrations are idempotent

set -Eeuo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR"

# Colored output
log() { printf "[\033[1;34mINFO\033[0m] %s\n" "$*"; }
ok() { printf "[\033[1;32m OK \033[0m] %s\n" "$*"; }
err() { printf "[\033[1;31mFAIL\033[0m] %s\n" "$*"; }

# Check if docker is available
if ! command -v docker &> /dev/null; then
    err "docker is not installed or not in PATH"
    exit 1
fi

# Check if database container is running
CONTAINER_RUNNING=$(docker ps --filter "name=logos-db" --format "{{.Names}}" 2>/dev/null)
if [ -z "$CONTAINER_RUNNING" ]; then
    err "logos-db container is not running"
    err "Start it with: docker compose up -d logos-db"
    exit 1
fi

echo "======================================"
echo "Logos Database Migrations"
echo "======================================"
echo ""

# List of migrations in order
MIGRATIONS=(
    "001_add_jobs_table.sql"
    "002_add_provider_sdi_columns.sql"
    "003a_drop_provider_ssh_columns.sql"
    "003b_create_model_provider_config.sql"
    "004_add_log_entry_sdi_columns.sql"
    "005_create_request_events_table.sql"
    "006_update_model_endpoints_to_local_ollama.sql"
    "007_rename_openwebui_to_ollama_no_auth.sql"
    "008_create_ollama_provider_snapshots.sql"
    "009_add_profile_id_to_jobs.sql"
    "010_remove_api_id_from_models.sql"
    "010b_revert_profile_constraint.sql"
    "011_restructure_model_api_keys_to_model_based.sql"
    "012_dedup_models_providers.sql"
    "013_set_ollama_provider_urls_and_auth.sql"
    "014_add_api_key_to_providers.sql"
    "015_add_snapshot_retention_cron.sql"
    "016_move_endpoint_to_model_api_keys.sql"
    "017_snapshot_provider_id_migration.sql"
    "018_drop_model_provider_config.sql"
    "019_add_request_id_to_log_entry.sql"
)

FAILED=0
SKIPPED=0
SUCCESS=0

for migration in "${MIGRATIONS[@]}"; do
    if [ ! -f "$migration" ]; then
        err "Migration file not found: $migration"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    log "Applying migration: $migration"

    if docker exec -i logos-db psql -U postgres -d logosdb -v ON_ERROR_STOP=1 < "$migration" > /dev/null 2>&1; then
        ok "$migration applied successfully"
        SUCCESS=$((SUCCESS + 1))
    else
        # Try to get error details
        ERROR=$(docker exec -i logos-db psql -U postgres -d logosdb -v ON_ERROR_STOP=1 < "$migration" 2>&1 || true)

        # Check if it's just a "already exists" warning (which is fine)
        if echo "$ERROR" | grep -iq "already exists"; then
            ok "$migration already applied (skipped)"
            SUCCESS=$((SUCCESS + 1))
        else
            err "Failed to apply $migration"
            echo "$ERROR" | head -5
            FAILED=$((FAILED + 1))
        fi
    fi
    echo ""
done

echo "======================================"
echo "Migration Summary"
echo "======================================"
echo ""
echo "✅ Success: $SUCCESS"
if [ $SKIPPED -gt 0 ]; then
    echo "⚠️  Skipped: $SKIPPED"
fi
if [ $FAILED -gt 0 ]; then
    echo "❌ Failed:  $FAILED"
fi
echo ""

if [ $FAILED -gt 0 ]; then
    err "Some migrations failed. Please review errors above."
    exit 1
else
    ok "All migrations completed successfully!"
    echo ""
    log "Verifying schema changes..."
    echo ""

    # Verify key tables exist
log "Checking for new tables..."
docker exec logos-db psql -U postgres -d logosdb -c "\dt" | grep -E "jobs|request_events|ollama_provider_snapshots" || true

    echo ""
    log "Checking providers table columns..."
    docker exec logos-db psql -U postgres -d logosdb -c "\d providers" | grep -E "provider_type|total_vram_mb|parallel_capacity|ollama_admin_url" || true

    echo ""
    log "Checking log_entry table columns..."
    docker exec logos-db psql -U postgres -d logosdb -c "\d log_entry" | grep -E "priority|queue_depth_at_arrival|was_cold_start" || true

    echo ""
    ok "Schema verification complete!"
fi
