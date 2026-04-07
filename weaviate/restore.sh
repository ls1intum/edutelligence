#!/bin/bash
set -e

# Load environment variables from .env file
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Configuration
BACKUP_DIR="./backups"
BACKUP_BACKEND="filesystem"
WEAVIATE_URL="https://${WEAVIATE_DOMAIN}"

# Check if backup ID was provided
if [ -z "$1" ]; then
    echo "Usage: $0 <backup-id>"
    echo ""
    echo "Available backups:"
    ls -1 "$BACKUP_DIR"/*.tar.gz 2>/dev/null | xargs -n 1 basename | sed 's/.tar.gz$//' || echo "  No backups found"
    exit 1
fi

BACKUP_ID="$1"
BACKUP_FILE="$BACKUP_DIR/$BACKUP_ID.tar.gz"

# Check if backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: Backup file not found: $BACKUP_FILE"
    echo ""
    echo "Available backups:"
    ls -1 "$BACKUP_DIR"/*.tar.gz 2>/dev/null | xargs -n 1 basename | sed 's/.tar.gz$//' || echo "  No backups found"
    exit 1
fi

# Check required environment variables
if [ -z "$WEAVIATE_API_KEY" ]; then
    echo "Error: WEAVIATE_API_KEY not set in .env file"
    exit 1
fi

if [ -z "$WEAVIATE_DOMAIN" ]; then
    echo "Error: WEAVIATE_DOMAIN not set in .env file"
    exit 1
fi

echo "======================================"
echo "WARNING: This will restore Weaviate to the state of backup: $BACKUP_ID"
echo "All current data will be replaced!"
echo "======================================"
echo ""
read -p "Are you sure you want to continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Restore cancelled"
    exit 0
fi

echo ""
echo "Extracting backup archive..."
tar -xzf "$BACKUP_FILE" -C "$BACKUP_DIR"

echo "Copying backup to Weaviate container..."
docker cp "$BACKUP_DIR/$BACKUP_ID" weaviate:/var/lib/weaviate/backups/$BACKUP_BACKEND/

echo "Initiating restore via Weaviate API..."
RESTORE_RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST \
    -H "Authorization: Bearer $WEAVIATE_API_KEY" \
    -H "Content-Type: application/json" \
    "$WEAVIATE_URL/v1/backups/$BACKUP_BACKEND/$BACKUP_ID/restore")

HTTP_CODE=$(echo "$RESTORE_RESPONSE" | tail -n1)
RESPONSE_BODY=$(echo "$RESTORE_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" != "200" ]; then
    echo "Error: Failed to initiate restore (HTTP $HTTP_CODE)"
    echo "Response: $RESPONSE_BODY"
    rm -rf "$BACKUP_DIR/$BACKUP_ID"
    exit 1
fi

echo "Restore initiated successfully"
echo ""

# Wait for restore to complete
echo "Waiting for restore to complete..."
MAX_RETRIES=60
RETRY_COUNT=0
SLEEP_INTERVAL=5

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    STATUS_RESPONSE=$(curl -s \
        -H "Authorization: Bearer $WEAVIATE_API_KEY" \
        "$WEAVIATE_URL/v1/backups/$BACKUP_BACKEND/$BACKUP_ID/restore")

    STATUS=$(echo "$STATUS_RESPONSE" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)

    if [ "$STATUS" = "SUCCESS" ]; then
        echo "Restore completed successfully!"
        break
    elif [ "$STATUS" = "FAILED" ]; then
        echo "Error: Restore failed"
        echo "Response: $STATUS_RESPONSE"
        rm -rf "$BACKUP_DIR/$BACKUP_ID"
        exit 1
    fi

    echo "Restore status: $STATUS (attempt $((RETRY_COUNT+1))/$MAX_RETRIES)"
    sleep $SLEEP_INTERVAL
    RETRY_COUNT=$((RETRY_COUNT+1))
done

# Clean up extracted backup directory
rm -rf "$BACKUP_DIR/$BACKUP_ID"

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "Error: Restore timed out after $((MAX_RETRIES*SLEEP_INTERVAL)) seconds"
    exit 1
fi

echo ""
echo "======================================"
echo "Restore completed successfully!"
echo "Backup ID: $BACKUP_ID"
echo "======================================"
