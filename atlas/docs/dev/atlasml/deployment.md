---
title: 'AtlasML Deployment Guide'
---

# AtlasML Deployment Guide

This guide covers deploying AtlasML to a production server with nginx as a reverse proxy for HTTPS termination.

## Architecture Overview

The production deployment consists of:
- **nginx**: Reverse proxy handling HTTPS/SSL termination on ports 80 and 443
- **atlasml**: FastAPI application running on port 80 (internal to Docker network)
- **Docker Compose**: Orchestrates both services in a shared network

```
Internet (HTTPS/443) → nginx → atlasml:80
```

## Prerequisites

- Docker and Docker Compose installed on the server
- SSL certificates (Let's Encrypt, organizational CA, or self-signed for testing)
- GitHub Container Registry access (or ability to build images locally)

## Deployment Methods

### Method 1: Using GitHub Actions (Recommended)

The repository includes automated deployment workflows that handle building and deploying the service.

#### Triggering a Deployment

1. Navigate to the **Actions** tab in GitHub
2. Select **"AtlasML - Deploy to Test 1"** workflow
3. Click **"Run workflow"**
4. Select your branch and configure:
   - `image-tag`: Docker image tag to deploy (e.g., `latest`, `pr-123`)
   - `deploy-atlasml`: Check to deploy AtlasML service
5. Click **"Run workflow"**

The workflow will:
- Provision environment variables on the VM
- Pull the specified Docker image
- Deploy using docker-compose

#### Required GitHub Secrets

Configure these secrets in your repository settings under **Settings > Secrets > Actions**:

**SSH Configuration:**
- `SSH_HOST`: VM hostname (e.g., `atlasml.aet.cit.tum.de`)
- `SSH_USERNAME`: SSH username
- `SSH_PRIVATE_KEY`: SSH private key for authentication

**Application Configuration:**
- `PYTHONPATH`: Python path (default: `/atlasml`)
- `WEAVIATE_HOST`: Weaviate server URL
- `WEAVIATE_PORT`: Weaviate HTTP port
- `WEAVIATE_GRPC_PORT`: Weaviate gRPC port
- `OPENAI_API_KEY`: Azure OpenAI API key
- `OPENAI_API_URL`: Azure OpenAI endpoint URL
- `ATLAS_API_KEYS`: JSON array of API keys (e.g., `["key1","key2"]`)
- `SENTRY_DSN`: Sentry DSN for error tracking
- `ENV`: Environment name (e.g., `production`)

### Method 2: Manual Deployment

For testing or when GitHub Actions is not available, you can deploy manually.

#### Step 1: Prepare the Server

See [Server Setup from Scratch](server-setup.md) for initial server configuration.

#### Step 2: Build or Pull Docker Image

**Option A: Pull from GitHub Container Registry**
```bash
sudo docker pull ghcr.io/ls1intum/edutelligence/atlasml:latest
```

**Option B: Build Locally on Server**
```bash
# Copy atlas directory to server
scp -r ./atlas <username>@<server>:~/

# SSH into server
ssh <username>@<server>

# Build image
cd ~/atlas/AtlasMl
sudo docker build -t atlasml:latest .
```

#### Step 3: Configure Environment

Create `/opt/atlasml/.env`:
```bash
sudo nano /opt/atlasml/.env
```

Add environment variables:
```env
PYTHONPATH=/atlasml
WEAVIATE_HOST=weaviate-test.ase.cit.tum.de
WEAVIATE_PORT=80
WEAVIATE_GRPC_PORT=443
OPENAI_API_KEY=your_key_here
OPENAI_API_URL=https://ase-se01.openai.azure.com
ATLAS_API_KEYS=["your_api_key"]
SENTRY_DSN=https://your_sentry_dsn
ENV=production
IMAGE_TAG=latest
```

Set proper permissions:
```bash
sudo chmod 600 /opt/atlasml/.env
```

#### Step 4: Deploy with Docker Compose

```bash
cd /opt/atlasml
sudo docker-compose -f compose.atlas.yaml up -d
```

#### Step 5: Verify Deployment

Check container status:
```bash
sudo docker-compose -f compose.atlas.yaml ps
```

View logs:
```bash
sudo docker-compose -f compose.atlas.yaml logs -f
```

Test endpoints:
```bash
# Test nginx health
curl http://localhost/health

# Test HTTPS endpoint
curl -k https://atlasml.aet.cit.tum.de/api/v1/health
```

## Docker Compose Configuration

The `compose.atlas.yaml` file defines two services:

### nginx Service

```yaml
nginx:
  image: nginx:alpine
  ports:
    - '80:80'
    - '443:443'
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf:ro
    - ./ssl:/etc/nginx/ssl:ro
  depends_on:
    atlasml:
      condition: service_healthy
```

### atlasml Service

```yaml
atlasml:
  image: 'ghcr.io/ls1intum/edutelligence/atlasml:${IMAGE_TAG}'
  env_file:
    - .env
  expose:
    - '80'
  healthcheck:
    test: ['CMD', 'python', '-c', 'import urllib.request; import sys; sys.exit(0 if urllib.request.urlopen("http://localhost:80/api/v1/health").getcode() == 200 else 1)']
```

## Managing the Deployment

### View Logs
```bash
sudo docker-compose -f /opt/atlasml/compose.atlas.yaml logs -f
```

### Restart Services
```bash
sudo docker-compose -f /opt/atlasml/compose.atlas.yaml restart
```

### Stop Services
```bash
sudo docker-compose -f /opt/atlasml/compose.atlas.yaml down
```

### Update to New Version
```bash
# Pull new image
sudo docker pull ghcr.io/ls1intum/edutelligence/atlasml:latest

# Recreate containers
cd /opt/atlasml
sudo docker-compose -f compose.atlas.yaml up -d --force-recreate
```

## Troubleshooting

### Container is Unhealthy

Check the health check endpoint manually:
```bash
sudo docker exec atlasml-atlasml-1 python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:80/api/v1/health').read().decode())"
```

### nginx Won't Start

Verify nginx configuration:
```bash
sudo docker run --rm -v /opt/atlasml/nginx.conf:/etc/nginx/nginx.conf:ro nginx:alpine nginx -t
```

### SSL Certificate Errors

Verify certificate files exist and have correct permissions:
```bash
ls -la /opt/atlasml/ssl/
```

### Application Errors

Check application logs:
```bash
sudo docker logs atlasml-atlasml-1
```

## See Also

- [Server Setup from Scratch](server-setup.md)
- [nginx Configuration](nginx.md)
- [API Documentation](api.md)
