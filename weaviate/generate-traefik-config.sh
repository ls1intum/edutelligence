#!/bin/bash
set -e

# Load environment variables from .env file
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Temporary files
TEMP_IPS=$(mktemp)
TEMP_OUTPUT=$(mktemp)

# Check if ALLOWED_IPS is set and not empty
if [ -z "$ALLOWED_IPS" ]; then
    echo "ALLOWED_IPS not set - using default config (public access with API key auth)"

    # Use permissive defaults (0.0.0.0/0 allows all IPs)
    echo '          - "0.0.0.0/0"' > "$TEMP_IPS"
else
    echo "ALLOWED_IPS set - restricting access to: $ALLOWED_IPS"

    # Convert comma-separated IPs to YAML array format
    IFS=',' read -ra IP_ARRAY <<< "$ALLOWED_IPS"
    > "$TEMP_IPS"  # Clear temp file

    for ip in "${IP_ARRAY[@]}"; do
        # Trim whitespace
        ip=$(echo "$ip" | xargs)
        if [ -n "$ip" ]; then
            echo "          - \"${ip}\"" >> "$TEMP_IPS"
        fi
    done
fi

# Generate config.yml from template by reading line by line
while IFS= read -r line; do
    if [[ "$line" == *"{{ALLOWED_IPS_YAML}}"* ]]; then
        # Replace placeholder with actual IP list
        cat "$TEMP_IPS"
    else
        echo "$line"
    fi
done < traefik/config.yml.template > "$TEMP_OUTPUT"

# Move output to final location
mv "$TEMP_OUTPUT" traefik/config.yml

# Clean up
rm -f "$TEMP_IPS"

echo "Generated traefik/config.yml successfully"
