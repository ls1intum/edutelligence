#!/bin/bash
set -e

echo "Setting up Weaviate infrastructure..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Error: .env file not found. Please copy .env.example to .env and configure it."
    exit 1
fi

# Create acme.json with proper permissions if it doesn't exist
if [ ! -f traefik/acme.json ]; then
    echo "Creating traefik/acme.json..."
    touch traefik/acme.json
fi

# Set proper permissions (600) for acme.json
echo "Setting permissions on traefik/acme.json..."
chmod 600 traefik/acme.json

# Generate Traefik config from template
echo "Generating Traefik configuration..."
./generate-traefik-config.sh

echo ""
echo "Setup complete! You can now run: docker-compose up -d"
echo ""
echo "Important reminders:"
echo "  1. Ensure your DNS records point to this server"
echo "  2. Ensure ports 80, 443, and 50051 are accessible"
echo "  3. Verify your .env file has secure credentials"
