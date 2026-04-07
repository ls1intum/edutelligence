#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${CONTAINER_NAME:-logos-db}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${ROOT_DIR}/db/backups"
MIGRATION_FILE="${ROOT_DIR}/db/migrations/012_dedup_models_providers.sql"

timestamp="$(date +"%Y%m%d_%H%M%S")"
mkdir -p "${BACKUP_DIR}"
backup_file="${BACKUP_DIR}/logos_${timestamp}.dump"

echo "Creating backup (container=${CONTAINER_NAME}): ${backup_file}"
docker exec -i "${CONTAINER_NAME}" sh -lc \
  'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "${backup_file}"

echo "Running migration: ${MIGRATION_FILE}"
docker exec -i "${CONTAINER_NAME}" sh -lc \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "${MIGRATION_FILE}"

echo "Done."
