#!/bin/bash
set -euo pipefail

# Production-grade TLS certificate generation for Hyperion gRPC
# This script generates self-signed certificates for development/testing
# For production, use certificates from a proper CA like Let's Encrypt

CERT_DIR="./certs"
DOMAIN="${1:-hyperion.local}"
DAYS=365

echo "🔐 Generating TLS certificates for Hyperion gRPC service..."
echo "Domain: $DOMAIN"
echo "Certificate directory: $CERT_DIR"

# Create certificate directory
mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

# Generate CA private key
echo "📋 Generating CA private key..."
openssl genrsa -out ca.key 4096

# Generate CA certificate
echo "📋 Generating CA certificate..."
openssl req -new -x509 -key ca.key -sha256 -subj "/C=DE/ST=Bavaria/L=Munich/O=TUM/CN=Hyperion-CA" -days $DAYS -out ca.crt

# Generate server private key
echo "📋 Generating server private key..."
openssl genrsa -out server.key 4096

# Generate server certificate signing request
echo "📋 Generating server certificate signing request..."
openssl req -subj "/C=DE/ST=Bavaria/L=Munich/O=TUM/CN=$DOMAIN" -new -key server.key -out server.csr

# Create extensions file for server certificate
cat > server.ext << EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = $DOMAIN
DNS.2 = localhost
DNS.3 = hyperion
DNS.4 = hyperion-service
IP.1 = 127.0.0.1
IP.2 = ::1
EOF

# Generate server certificate signed by CA
echo "📋 Generating server certificate..."
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days $DAYS -sha256 -extfile server.ext

# Generate client private key (for mTLS)
echo "📋 Generating client private key..."
openssl genrsa -out client.key 4096

# Generate client certificate signing request
echo "📋 Generating client certificate signing request..."
openssl req -subj "/C=DE/ST=Bavaria/L=Munich/O=TUM/CN=artemis-client" -new -key client.key -out client.csr

# Generate client certificate signed by CA
echo "📋 Generating client certificate..."
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days $DAYS -sha256

# Set proper permissions
chmod 600 *.key
chmod 644 *.crt

# Clean up CSR files
rm -f *.csr *.ext

echo "✅ TLS certificates generated successfully!"
echo ""
echo "📁 Generated files in $CERT_DIR:"
echo "   ca.crt      - Certificate Authority certificate"
echo "   ca.key      - Certificate Authority private key"
echo "   server.crt  - Server certificate"
echo "   server.key  - Server private key"
echo "   client.crt  - Client certificate (for mTLS)"
echo "   client.key  - Client private key (for mTLS)"
echo ""
echo "🚀 To use with Hyperion:"
echo "   1. Set TLS_ENABLED=true in your .env file"
echo "   2. Set TLS_CERT_PATH=/certs/server.crt"
echo "   3. Set TLS_KEY_PATH=/certs/server.key"
echo "   4. Set TLS_CA_PATH=/certs/ca.crt (for client verification)"
echo ""
echo "🔍 Verify certificate:"
echo "   openssl x509 -in $CERT_DIR/server.crt -text -noout"
echo ""
echo "🧪 Test gRPC connection:"
echo "   grpcurl -cacert $CERT_DIR/ca.crt $DOMAIN:50051 list"
