---
title: "AtlasML Installation Guide"
description: "Step-by-step guide to installing AtlasML on production servers"
sidebar_position: 2
---

# AtlasML Installation Guide

This guide walks you through installing AtlasML on a production server. For local development setup, see the [Setup Guide](/dev/setup).

---

## Prerequisites

Before installing AtlasML, ensure your server meets these requirements:

### System Requirements

**Minimum**:
- **CPU**: 2 cores
- **RAM**: 2GB
- **Disk**: 10GB + storage for Weaviate data
- **OS**: Linux (Ubuntu 20.04+ recommended)

**Recommended for Production**:
- **CPU**: 4+ cores
- **RAM**: 4GB+
- **Disk**: 50GB SSD
- **OS**: Ubuntu 22.04 LTS

### Software Requirements

```bash
# Docker
Docker 20.10+
Docker Compose 2.0+

# Network access
- Outbound HTTPS to OpenAI API (*.openai.azure.com)
- Outbound HTTPS to GitHub Container Registry (ghcr.io)
- Inbound access from Artemis server
```

---

## Installation with Docker Compose

Docker Compose is the **only supported method** for production deployments.

:::warning
For local development setup, see the [Development Setup Guide](/dev/setup). Manual installation is not supported for production.
:::

### Step 1: Install Docker

```bash
# Update packages
sudo apt-get update

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Verify installation
docker --version
# Should show: Docker version 20.10+ or higher

# Add user to docker group (optional)
sudo usermod -aG docker $USER
newgrp docker
```

### Step 2: Install Docker Compose

```bash
# Download Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose

# Make executable
sudo chmod +x /usr/local/bin/docker-compose

# Verify installation
docker-compose --version
# Should show: Docker Compose version 2.0+ or higher
```

### Step 3: Create Installation Directory

```bash
# Create directory
sudo mkdir -p /opt/atlasml
cd /opt/atlasml

# Set permissions
sudo chown $USER:$USER /opt/atlasml
```

### Step 4: Download Configuration Files

```bash
# Download production Docker Compose file
curl -o docker-compose.prod.yml https://raw.githubusercontent.com/ls1intum/edutelligence/main/atlas/docker-compose.prod.yml

# Download environment template
curl -o .env.example https://raw.githubusercontent.com/ls1intum/edutelligence/main/atlas/.env.example

# Create Traefik configuration directory
mkdir -p traefik

# Download Traefik configuration files
curl -o traefik/traefik.yml https://raw.githubusercontent.com/ls1intum/edutelligence/main/atlas/traefik/traefik.yml
curl -o traefik/config.yml https://raw.githubusercontent.com/ls1intum/edutelligence/main/atlas/traefik/config.yml

# Create SSL certificate file with correct permissions
touch traefik/acme.json
chmod 600 traefik/acme.json
```

### Step 5: Set Up Weaviate

AtlasML requires Weaviate as its vector database. **Use the centralized Weaviate setup** in the `/weaviate` directory.

:::warning Required
AtlasML requires the centralized Weaviate setup with Traefik and API key authentication. Other Weaviate deployment methods are **not supported**.
:::

**Follow the Weaviate setup instructions:**

1. Navigate to the weaviate directory:
   ```bash
   cd /path/to/edutelligence/weaviate
   ```

2. Follow the complete setup guide in the [Weaviate README](https://github.com/ls1intum/edutelligence/blob/main/weaviate/README.md), which includes:
   - Docker and Traefik configuration
   - SSL/TLS certificates via Let's Encrypt
   - API key authentication setup
   - Production-ready configuration

3. After Weaviate is running, verify it's accessible:
   ```bash
   curl -H "Authorization: Bearer YOUR_WEAVIATE_API_KEY" https://your-weaviate-domain.com/v1/.well-known/ready
   # Should return: {"status":"ok"}
   ```

4. **Save the following for AtlasML configuration:**
   - Weaviate domain (e.g., `weaviate.example.com`)
   - Weaviate API key
   - Weaviate ports: `443` (HTTPS), `50051` (gRPC)

### Step 6: Create Environment File

See [Configuration Guide](./atlasml-configuration.md) for detailed explanation of each variable.

```bash
cat > /opt/atlasml/.env << 'EOF'
# API Authentication (comma-separated)
ATLAS_API_KEYS=your-secure-api-key-here

# Weaviate Connection (from centralized Weaviate setup)
WEAVIATE_HOST=https://your-weaviate-domain.com
WEAVIATE_PORT=443
WEAVIATE_GRPC_PORT=50051
WEAVIATE_API_KEY=your-weaviate-api-key

# OpenAI Configuration (Azure)
OPENAI_API_KEY=your-openai-api-key
OPENAI_API_URL=https://your-resource.openai.azure.com

# Environment
ENV=production

# Sentry Error Tracking (optional)
SENTRY_DSN=https://...@sentry.../6

# Python Path (default is usually fine)
PYTHONPATH=/atlasml

# Image Tag
IMAGE_TAG=main
EOF

# Secure the file
chmod 600 /opt/atlasml/.env
```

:::tip
Use the same `WEAVIATE_API_KEY` that you configured in the centralized Weaviate setup (`/weaviate/.env`).
:::

:::warning Security
Never commit the `.env` file to version control. Keep your API keys secure.
:::

### Step 7: Pull and Start AtlasML

```bash
cd /opt/atlasml

# Pull the image
docker-compose -f docker-compose.prod.yml pull

# Start the service
docker-compose -f docker-compose.prod.yml up -d

# Check status
docker-compose -f docker-compose.prod.yml ps
```

**Expected output**:
```
NAME      IMAGE                                   STATUS    PORTS
atlasml   ghcr.io/ls1intum/edutelligence/atlasml  healthy   0.0.0.0:80->8000/tcp
```

### Step 8: Verify Installation

```bash
# Check health endpoint
curl http://localhost/api/v1/health

# Should return: []

# Check logs
docker logs atlasml

# Should see:
# INFO:     Started server process
# INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

## Post-Installation

### 1. Configure Firewall

```bash
# Allow HTTP/HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Allow only from Artemis server (recommended)
sudo ufw allow from ARTEMIS_SERVER_IP to any port 80
```

### 2. Set Up Reverse Proxy (Nginx)

For HTTPS support:

```bash
# Install Nginx
sudo apt-get install nginx certbot python3-certbot-nginx

# Create configuration
sudo cat > /etc/nginx/sites-available/atlasml << 'EOF'
server {
    listen 443 ssl http2;
    server_name atlasml.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/atlasml.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/atlasml.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://localhost:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/atlasml /etc/nginx/sites-enabled/

# Get SSL certificate
sudo certbot --nginx -d atlasml.yourdomain.com

# Reload Nginx
sudo systemctl reload nginx
```

### 3. Enable Auto-Start

With docker-compose and `restart: unless-stopped`, containers will automatically start on boot.

Verify:
```bash
sudo systemctl enable docker
```

### 4. Set Up Monitoring

See [Monitoring Guide](./atlasml-monitoring.md) for detailed monitoring setup.

---

## Updating AtlasML

### Update to Latest Version

```bash
cd /opt/atlasml

# Pull new image
docker-compose -f docker-compose.prod.yml pull

# Restart service (zero downtime if using load balancer)
docker-compose -f docker-compose.prod.yml up -d

# Verify
docker logs atlasml
```

### Update to Specific Version

```bash
# Set version in .env
echo "IMAGE_TAG=v1.2.0" >> /opt/atlasml/.env

# Pull and restart
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d
```

---

## Backup and Restore

### Backup Weaviate Data

```bash
# Stop Weaviate
docker-compose -f compose.weaviate.yaml stop

# Backup data directory
sudo tar -czf weaviate-backup-$(date +%Y%m%d).tar.gz /var/lib/docker/volumes/weaviate-data

# Restart Weaviate
docker-compose -f compose.weaviate.yaml start
```

### Restore Weaviate Data

```bash
# Stop Weaviate
docker-compose -f compose.weaviate.yaml down

# Restore data
sudo tar -xzf weaviate-backup-20250101.tar.gz -C /

# Start Weaviate
docker-compose -f compose.weaviate.yaml up -d
```

---

## Uninstallation

### Remove AtlasML

```bash
# Stop and remove containers
docker-compose -f docker-compose.prod.yml down

# Remove images
docker rmi ghcr.io/ls1intum/edutelligence/atlasml:main

# Remove data (optional)
sudo rm -rf /opt/atlasml
```

### Remove Weaviate

```bash
# Stop and remove containers
docker-compose -f compose.weaviate.yaml down -v

# This removes the Weaviate data volume
```

---

## Troubleshooting Installation

### Docker Installation Fails

**Issue**: `curl -fsSL https://get.docker.com` fails

**Solution**:
```bash
# Manual installation (Ubuntu)
sudo apt-get update
sudo apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io
```

### Image Pull Fails

**Issue**: `Error response from daemon: pull access denied`

**Solution**:
```bash
# Login to GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin

# Or use public access
docker pull ghcr.io/ls1intum/edutelligence/atlasml:main
```

### Container Won't Start

**Check logs**:
```bash
docker logs atlasml
```

**Common issues**:
1. Missing environment variables → Check `.env` file
2. Weaviate not running → Start Weaviate first
3. Port already in use → Change port in compose file

### Health Check Failing

**Test manually**:
```bash
curl http://localhost/api/v1/health
```

**If fails**, check:
1. Container is running: `docker ps`
2. Logs: `docker logs atlasml`
3. Network: `docker network inspect shared-network`

---

## Next Steps

1. **[Configuration](./atlasml-configuration.md)**: Configure environment variables and secrets
2. **[Deployment](./atlasml-deployment.md)**: Set up automated deployment workflows
3. **[Monitoring](./atlasml-monitoring.md)**: Monitor health and performance
4. **[Troubleshooting](./atlasml-troubleshooting.md)**: Resolve production issues

---

## Resources

- **Docker Documentation**: https://docs.docker.com/
- **Docker Compose**: https://docs.docker.com/compose/
- **Weaviate Installation**: https://weaviate.io/developers/weaviate/installation
