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
if ! docker ps | grep -q logos-db; then
    err "logos-db container is not running"
    exit 1
fi

echo "======================================"
echo "Logos Database Migrations"
echo "======================================"
echo ""

# List of migrations in order
MIGRATIONS=(
    "001_add_provider_ssh_columns.sql"
    "002_add_provider_sdi_columns.sql"
    "003_create_model_provider_config.sql"
    "004_add_log_entry_sdi_columns.sql"
    "005_create_request_events_table.sql"
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

    if docker exec -i logos-db psql -U postgres -d logosdb < "$migration" > /dev/null 2>&1; then
        ok "$migration applied successfully"
        SUCCESS=$((SUCCESS + 1))
    else
        # Try to get error details
        ERROR=$(docker exec -i logos-db psql -U postgres -d logosdb < "$migration" 2>&1 || true)

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
    docker exec logos-db psql -U postgres -d logosdb -c "\dt" | grep -E "model_provider_config|request_events" || true

    echo ""
    log "Checking providers table columns..."
    docker exec logos-db psql -U postgres -d logosdb -c "\d providers" | grep -E "provider_type|ssh_host|total_vram_mb|parallel_capacity" || true

    echo ""
    ok "Schema verification complete!"
fi
