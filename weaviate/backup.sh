#!/bin/bash
set -e

# Load environment variables from .env file
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Configuration
BACKUP_ID="backup-$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="./backups"
BACKUP_BACKEND="filesystem"
WEAVIATE_URL="https://${WEAVIATE_DOMAIN}"

# Check required environment variables
if [ -z "$WEAVIATE_API_KEY" ]; then
    echo "Error: WEAVIATE_API_KEY not set in .env file"
    exit 1
fi

if [ -z "$WEAVIATE_DOMAIN" ]; then
    echo "Error: WEAVIATE_DOMAIN not set in .env file"
    exit 1
fi

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "Starting Weaviate backup: $BACKUP_ID"
echo "Backup URL: $WEAVIATE_URL"
echo ""

# Initiate backup via Weaviate API
echo "Initiating backup..."
BACKUP_RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST \
    -H "Authorization: Bearer $WEAVIATE_API_KEY" \
    -H "Content-Type: application/json" \
    "$WEAVIATE_URL/v1/backups/$BACKUP_BACKEND" \
    -d "{\"id\": \"$BACKUP_ID\"}")

HTTP_CODE=$(echo "$BACKUP_RESPONSE" | tail -n1)
RESPONSE_BODY=$(echo "$BACKUP_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" != "200" ]; then
    echo "Error: Failed to initiate backup (HTTP $HTTP_CODE)"
    echo "Response: $RESPONSE_BODY"
    exit 1
fi

echo "Backup initiated successfully"
echo ""

# Wait for backup to complete
echo "Waiting for backup to complete..."
MAX_RETRIES=60
RETRY_COUNT=0
SLEEP_INTERVAL=5

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    STATUS_RESPONSE=$(curl -s \
        -H "Authorization: Bearer $WEAVIATE_API_KEY" \
        "$WEAVIATE_URL/v1/backups/$BACKUP_BACKEND/$BACKUP_ID")

    STATUS=$(echo "$STATUS_RESPONSE" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)

    if [ "$STATUS" = "SUCCESS" ]; then
        echo "Backup completed successfully!"
        break
    elif [ "$STATUS" = "FAILED" ]; then
        echo "Error: Backup failed"
        echo "Response: $STATUS_RESPONSE"
        exit 1
    fi

    echo "Backup status: $STATUS (attempt $((RETRY_COUNT+1))/$MAX_RETRIES)"
    sleep $SLEEP_INTERVAL
    RETRY_COUNT=$((RETRY_COUNT+1))
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "Error: Backup timed out after $((MAX_RETRIES*SLEEP_INTERVAL)) seconds"
    exit 1
fi

echo ""
echo "Copying backup from Weaviate container..."

# Copy backup from Weaviate container to local backup directory
docker cp weaviate:/var/lib/weaviate/backups/$BACKUP_BACKEND/$BACKUP_ID "$BACKUP_DIR/"

# Create compressed archive
echo "Creating compressed archive..."
tar -czf "$BACKUP_DIR/$BACKUP_ID.tar.gz" -C "$BACKUP_DIR" "$BACKUP_ID"

# Remove uncompressed backup directory
rm -rf "$BACKUP_DIR/$BACKUP_ID"

echo ""
echo "======================================"
echo "Backup completed successfully!"
echo "Backup ID: $BACKUP_ID"
echo "Location: $BACKUP_DIR/$BACKUP_ID.tar.gz"
echo "Size: $(du -h "$BACKUP_DIR/$BACKUP_ID.tar.gz" | cut -f1)"
echo "======================================"
echo ""
echo "To restore this backup, run:"
echo "  ./restore.sh $BACKUP_ID"
