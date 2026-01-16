---
title: "AtlasML Configuration Guide"
description: "Complete guide to configuring AtlasML environment variables and settings"
sidebar_position: 4
---

# AtlasML Configuration Guide

This guide covers all configuration options for AtlasML, including environment variables, secrets management, and environment-specific configurations.

---

## Configuration Overview

AtlasML is configured primarily through **environment variables**, which can be set via:

1. **`.env` file** (recommended for production)
2. **Docker Compose** environment section
3. **System environment variables**

---

## Required Environment Variables

These variables **must** be set for AtlasML to function:

### API Authentication

```bash
ATLAS_API_KEYS=key1,key2,key3
```

**Description**: Comma-separated list of API keys for authenticating requests from Artemis.

**Format**: Comma-separated string (no spaces around commas recommended)

**Example**:
```bash
# Single key
ATLAS_API_KEYS=my-secure-api-key-2025

# Multiple keys (for key rotation)
ATLAS_API_KEYS=current-key,backup-key

# Production example
ATLAS_API_KEYS=prod-key-artemis-1,prod-key-artemis-2
```

**Security Notes**:
- Use strong, random keys (32+ characters)
- Rotate keys regularly (quarterly recommended)
- Never commit keys to version control
- Use different keys per environment

**Generate secure key**:
```bash
# Using openssl
openssl rand -hex 32

# Using Python
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Example output: "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
```

---

### Weaviate Connection

```bash
WEAVIATE_HOST=https://your-weaviate-domain.com
WEAVIATE_PORT=443
WEAVIATE_GRPC_PORT=50051
WEAVIATE_API_KEY=your-weaviate-api-key
```

:::warning Required Setup
AtlasML requires the **centralized Weaviate setup** located in `/weaviate` directory. See the [Weaviate README](https://github.com/ls1intum/edutelligence/blob/main/weaviate/README.md) for complete setup instructions.
:::

**WEAVIATE_HOST**:
- **Description**: Full HTTPS URL of the centralized Weaviate instance
- **Format**: `https://your-weaviate-domain.com`
- **Required**: Must match the domain configured in `/weaviate/.env`
- **Example**: `https://weaviate.example.com`

**WEAVIATE_PORT**:
- **Description**: HTTPS port for Weaviate REST API
- **Default**: `443`
- **Required**: Must be `443` (centralized setup uses Traefik with HTTPS)

**WEAVIATE_GRPC_PORT**:
- **Description**: gRPC port for Weaviate (required by Weaviate Python client v4)
- **Default**: `50051`
- **Required**: Yes - the Weaviate Python client v4 requires gRPC for optimal performance
- **Note**: This port must be accessible from AtlasML to the Weaviate server

**WEAVIATE_API_KEY**:
- **Description**: API key for authenticating with Weaviate
- **Required**: Yes (centralized Weaviate requires authentication)
- **Source**: Use the same API key from `/weaviate/.env`
- **Security**: Keep this key secure and never commit to version control

**Production Configuration Example**:

```bash
# Production (using centralized Weaviate with REST API only)
WEAVIATE_HOST=https://weaviate.example.com
WEAVIATE_PORT=443
WEAVIATE_API_KEY=your-secure-weaviate-api-key-from-weaviate-env
```

---

### OpenAI Configuration

```bash
OPENAI_API_KEY=your-api-key
OPENAI_API_URL=https://your-resource.openai.azure.com
```

**OPENAI_API_KEY**:
- **Description**: Azure OpenAI API key for generating embeddings
- **Required**: Yes (for production-quality embeddings)
- **Optional**: Can use local embeddings if not set
- **Format**: String (32-64 characters)

**OPENAI_API_URL**:
- **Description**: Base URL for Azure OpenAI API
- **Format**: `https://{resource-name}.openai.azure.com`
- **Example**: `https://ase-se01.openai.azure.com`

**Get Azure OpenAI credentials**:
1. Go to Azure Portal
2. Navigate to Azure OpenAI resource
3. Go to "Keys and Endpoint"
4. Copy:
   - KEY 1 → `OPENAI_API_KEY`
   - Endpoint → `OPENAI_API_URL`

**Environment-specific examples**:

```bash
# Development (using test keys)
OPENAI_API_KEY=dev-test-key-abc123
OPENAI_API_URL=https://dev-openai.openai.azure.com

# Staging
OPENAI_API_KEY=staging-key-xyz789
OPENAI_API_URL=https://staging-openai.openai.azure.com

# Production
OPENAI_API_KEY=prod-key-secure-2025
OPENAI_API_URL=https://prod-openai.openai.azure.com
```

**Using local embeddings (no OpenAI)**:

If `OPENAI_API_KEY` is not set, AtlasML falls back to local SentenceTransformer models:

```bash
# Leave empty or unset
OPENAI_API_KEY=
OPENAI_API_URL=

# AtlasML will use: sentence-transformers/all-mpnet-base-v2
```

**Trade-offs**:
- **Azure OpenAI**: Higher quality, faster, requires API key and costs money
- **Local models**: Free, works offline, but lower quality embeddings

---

## Optional Environment Variables

### Environment Name

```bash
ENV=production
```

**Description**: Environment identifier for logging and monitoring

**Values**:
- `development`: Local development
- `staging`: Staging/test environment
- `production`: Production environment

**Default**: `development`

**Used for**:
- Sentry environment tagging
- Log formatting
- Feature flags (if implemented)

---

### Python Path

```bash
PYTHONPATH=/atlasml
```

**Description**: Python module search path

**Default**: `/atlasml` (inside Docker container)

**When to change**: Rarely needed unless custom installation path

---

### Sentry Error Tracking

```bash
SENTRY_DSN=https://examplePublicKey@o0.ingest.sentry.io/0
```

**Description**: Sentry DSN (Data Source Name) for error tracking

**Format**: `https://{public-key}@{organization}.ingest.sentry.io/{project-id}`

**How to get**:
1. Create account at https://sentry.io
2. Create new project (Python/FastAPI)
3. Copy DSN from project settings

**Example**:
```bash
SENTRY_DSN=https://abc123def456@o123456.ingest.sentry.io/7891011
```

**If not set**: Error tracking disabled (errors only logged locally)

**Benefits**:
- Automatic error reporting
- Stack traces
- Release tracking
- Performance monitoring
- User context

---

### Image Tag (Docker Compose)

```bash
IMAGE_TAG=main
```

**Description**: Docker image tag to pull

**Examples**:
```bash
# Latest main branch
IMAGE_TAG=main

# Specific version
IMAGE_TAG=v1.2.0

# Feature branch
IMAGE_TAG=feature-new-embeddings

# PR image
IMAGE_TAG=pr-123
```

**Used in**: `docker-compose.prod.yml`

```yaml
image: 'ghcr.io/ls1intum/edutelligence/atlasml:${IMAGE_TAG}'
```

---

## Configuration File Examples

### Development Configuration

```bash
# .env.development

# API Keys (development)
ATLAS_API_KEYS=dev-test-key

# Weaviate (centralized setup - required)
WEAVIATE_HOST=https://weaviate-dev.example.com
WEAVIATE_PORT=443
WEAVIATE_API_KEY=dev-weaviate-api-key

# OpenAI (optional for dev)
OPENAI_API_KEY=
OPENAI_API_URL=

# Environment
ENV=development
PYTHONPATH=/atlasml

# Sentry (optional)
SENTRY_DSN=

# Image
IMAGE_TAG=main
```

:::note
Even for development, use the centralized Weaviate setup. For local development without Weaviate, see the [Development Setup Guide](/dev/setup).
:::

---

### Staging Configuration

```bash
# .env.staging

# API Keys (staging)
ATLAS_API_KEYS=staging-key-1,staging-key-2

# Weaviate (centralized setup)
WEAVIATE_HOST=https://weaviate-staging.example.com
WEAVIATE_PORT=443
WEAVIATE_API_KEY=staging-weaviate-api-key

# OpenAI (staging)
OPENAI_API_KEY=staging-azure-openai-key
OPENAI_API_URL=https://staging-resource.openai.azure.com

# Environment
ENV=staging
PYTHONPATH=/atlasml

# Sentry (staging)
SENTRY_DSN=https://abc@o123.ingest.sentry.io/456

# Image
IMAGE_TAG=develop
```

---

### Production Configuration

```bash
# .env.production

# API Keys (production - KEEP SECURE!)
ATLAS_API_KEYS=prod-artemis-key-2025-q1,prod-artemis-key-2025-q1-backup

# Weaviate (centralized setup)
WEAVIATE_HOST=https://weaviate.example.com
WEAVIATE_PORT=443
WEAVIATE_API_KEY=prod-weaviate-api-key-secure

# OpenAI (production)
OPENAI_API_KEY=prod-azure-openai-key-secure
OPENAI_API_URL=https://prod-resource.openai.azure.com

# Environment
ENV=production
PYTHONPATH=/atlasml

# Sentry (production)
SENTRY_DSN=https://prodkey@o123.ingest.sentry.io/789

# Image (specific version for production)
IMAGE_TAG=v1.2.0
```

---

## Secrets Management

### Option 1: .env File (Recommended for Single Server)

**Setup**:
```bash
# Create file
sudo nano /opt/atlasml/.env

# Set secure permissions (read only by owner)
sudo chmod 600 /opt/atlasml/.env
sudo chown atlasml:atlasml /opt/atlasml/.env
```

**Load in Docker Compose**:
```yaml
services:
  atlasml:
    env_file:
      - .env
```

**Pros**:
- Simple
- Easy to update
- Works with docker-compose

**Cons**:
- File can be read if server is compromised
- No encryption at rest
- Manual rotation

---

### Option 2: Docker Secrets (Swarm/Compose)

**Create secret**:
```bash
# From file
docker secret create atlas_api_keys /path/to/keys.txt

# From stdin
echo "my-secret-key" | docker secret create atlas_api_key -
```

**Use in Compose**:
```yaml
services:
  atlasml:
    secrets:
      - atlas_api_keys
    environment:
      ATLAS_API_KEYS_FILE: /run/secrets/atlas_api_keys

secrets:
  atlas_api_keys:
    external: true
```

**Pros**:
- Encrypted at rest and in transit
- Managed by Docker
- Automatic rotation support

**Cons**:
- Requires Docker Swarm or specific setup
- More complex configuration

---

### Option 3: External Secrets Manager

Use HashiCorp Vault, AWS Secrets Manager, Azure Key Vault, etc.

**Example with Vault**:
```bash
# Store secret
vault kv put secret/atlasml/prod \
  api_keys='["key1","key2"]' \
  openai_key='your-key'

# Retrieve and export
export ATLAS_API_KEYS=$(vault kv get -field=api_keys secret/atlasml/prod)
export OPENAI_API_KEY=$(vault kv get -field=openai_key secret/atlasml/prod)

# Run container
docker run -e ATLAS_API_KEYS -e OPENAI_API_KEY atlasml:latest
```

**Pros**:
- Centralized secrets management
- Audit logging
- Automatic rotation
- Access control

**Cons**:
- Additional infrastructure
- More complexity

---

## Configuration Validation

### Check Configuration

```bash
# View current configuration (masks secrets)
docker exec atlasml env | grep -E "(WEAVIATE|OPENAI|ATLAS|ENV)"

# Mask sensitive values
docker exec atlasml env | grep -E "(WEAVIATE|OPENAI|ATLAS|ENV)" | sed 's/=.*/=***/'
```

### Test Configuration

```bash
# Test Weaviate connection (HTTPS production example)
curl ${WEAVIATE_HOST}/v1/.well-known/ready
# For local/dev without scheme, use:
# curl http://${WEAVIATE_HOST}:${WEAVIATE_PORT}/v1/.well-known/ready

# Test AtlasML health
curl http://localhost/api/v1/health

# Test with API key
curl -H "Authorization: your-key" http://localhost/api/v1/competency/suggest \
  -H "Content-Type: application/json" \
  -d '{"description":"test","course_id":1}'
```

### Common Configuration Errors

**Error**: `Invalid API key`
```bash
# Check ATLAS_API_KEYS format
echo $ATLAS_API_KEYS
# Should be: ["key1","key2"]
# NOT: ["key1", "key2"] (no spaces)
# NOT: [key1,key2] (missing quotes)
```

**Error**: `Weaviate connection failed`
```bash
# Check connectivity (HTTPS production example)
curl ${WEAVIATE_HOST}/v1/.well-known/ready
# For local/dev without scheme, use:
# curl http://${WEAVIATE_HOST}:${WEAVIATE_PORT}/v1/.well-known/ready

# Check from container
docker exec atlasml curl ${WEAVIATE_HOST}/v1/.well-known/ready
# For local/dev without scheme, use:
# docker exec atlasml curl http://${WEAVIATE_HOST}:${WEAVIATE_PORT}/v1/.well-known/ready
```

**Error**: `OpenAI API error`
```bash
# Test API key
curl https://${OPENAI_API_URL}/openai/deployments \
  -H "api-key: ${OPENAI_API_KEY}"
```

---

## Configuration Best Practices

### 1. Use Strong API Keys

```bash
# ✅ Good - 32+ characters, random
ATLAS_API_KEYS=8h7f6e5d4c3b2a1z9y8x7w6v5u4t3s2r

# ❌ Bad - Short, predictable
ATLAS_API_KEYS=test,password123
```

### 2. Separate Environments

```bash
# ✅ Good - Different keys per environment
# .env.dev:   ATLAS_API_KEYS=dev-key
# .env.prod:  ATLAS_API_KEYS=prod-key

# ❌ Bad - Same keys everywhere
```

### 3. Rotate Keys Regularly

```bash
# Support multiple keys for zero-downtime rotation
ATLAS_API_KEYS=current-key,new-key

# Process:
# 1. Add new key
# 2. Update Artemis to use new key
# 3. Remove old key
```

### 4. Never Commit Secrets

```bash
# .gitignore
.env
.env.*
*.key
*.pem
secrets/
```

### 5. Use Least Privilege

- Weaviate: Only allow AtlasML to access
- OpenAI: Use resource-specific keys, not account-wide
- API keys: Generate separate keys per client

### 6. Document Configuration

```bash
# .env.example (commit this)
ATLAS_API_KEYS=REPLACE_WITH_YOUR_KEY
WEAVIATE_HOST=localhost
WEAVIATE_PORT=8085
OPENAI_API_KEY=REPLACE_WITH_YOUR_KEY
OPENAI_API_URL=https://your-resource.openai.azure.com
ENV=production
```

### 7. Monitor Configuration Changes

- Log configuration changes
- Alert on unexpected changes
- Audit access to secrets

---

## Troubleshooting Configuration

### Issue: Environment Variables Not Loading

**Check**:
```bash
# View all env vars in container
docker exec atlasml env

# Check specific variable
docker exec atlasml printenv ATLAS_API_KEYS
```

**Common causes**:
- `.env` file not in correct location
- File permissions too restrictive
- Syntax errors in `.env`

### Issue: API Key Not Working

**Debug**:
```bash
# Check format
echo $ATLAS_API_KEYS
# Must be comma-separated

# Test with curl (use first key if multiple)
KEY=$(echo $ATLAS_API_KEYS | cut -d',' -f1)
curl -H "Authorization: $KEY" \
  http://localhost/api/v1/health
```

### Issue: Weaviate Connection Timeout

**Check network**:
```bash
# Check DNS resolution
nslookup your-weaviate-domain.com

# Test connection with API key
curl -H "Authorization: Bearer YOUR_WEAVIATE_API_KEY" https://your-weaviate-domain.com/v1/.well-known/ready

# From AtlasML container
docker exec atlasml curl -H "Authorization: Bearer ${WEAVIATE_API_KEY}" ${WEAVIATE_HOST}/v1/.well-known/ready

# Check if Weaviate server is running (SSH to Weaviate server)
cd /path/to/edutelligence/weaviate
docker-compose ps weaviate
```

---

## Next Steps

- **[Installation](./atlasml-installation.md)**: Install AtlasML with proper configuration
- **[Deployment](./atlasml-deployment.md)**: Deploy with environment-specific configs
- **[Monitoring](./atlasml-monitoring.md)**: Monitor configuration-related issues
- **[Troubleshooting](./atlasml-troubleshooting.md)**: Resolve configuration problems

---

## Resources

- **Docker Environment Variables**: https://docs.docker.com/compose/environment-variables/
- **Docker Secrets**: https://docs.docker.com/engine/swarm/secrets/
- **Azure OpenAI**: https://azure.microsoft.com/en-us/products/ai-services/openai-service
