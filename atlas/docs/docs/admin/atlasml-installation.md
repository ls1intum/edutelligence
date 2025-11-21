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

## Installation Methods

### Method 1: Docker Compose (Recommended)

This is the simplest method for single-server deployments.

#### Step 1: Install Docker

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

#### Step 2: Install Docker Compose

```bash
# Download Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose

# Make executable
sudo chmod +x /usr/local/bin/docker-compose

# Verify installation
docker-compose --version
# Should show: Docker Compose version 2.0+ or higher
```

#### Step 3: Create Installation Directory

```bash
# Create directory
sudo mkdir -p /opt/atlasml
cd /opt/atlasml

# Set permissions
sudo chown $USER:$USER /opt/atlasml
```

#### Step 4: Download Compose File

```bash
# Download from GitHub
curl -o compose.atlas.yaml https://raw.githubusercontent.com/ls1intum/edutelligence/main/atlas/compose.atlas.yaml

# Or create manually
cat > compose.atlas.yaml << 'EOF'
services:
  atlasml:
    image: 'ghcr.io/ls1intum/edutelligence/atlasml:${IMAGE_TAG}'
    env_file:
      - .env
    environment:
      PYTHONPATH: ${PYTHONPATH:-/atlasml}
      WEAVIATE_HOST: ${WEAVIATE_HOST}
      WEAVIATE_PORT: ${WEAVIATE_PORT:-80}
      WEAVIATE_GRPC_PORT: ${WEAVIATE_GRPC_PORT:-443}
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      OPENAI_API_URL: ${OPENAI_API_URL}
      ATLAS_API_KEYS: ${ATLAS_API_KEYS}
      SENTRY_DSN: ${SENTRY_DSN}
      ENV: ${ENV:-production}
    restart: unless-stopped
    ports:
      - '80:8000'
    networks:
      - shared-network
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:8000/api/v1/health']
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    logging:
      driver: 'json-file'
      options:
        max-size: '50m'
        max-file: '5'

networks:
  shared-network:
    name: shared-network
    driver: bridge
EOF
```

#### Step 5: Install Weaviate

AtlasML requires Weaviate as its vector database.

```bash
# Download Weaviate compose file
curl -o compose.weaviate.yaml https://raw.githubusercontent.com/ls1intum/edutelligence/main/atlas/compose.weaviate.yaml

# Or create manually
cat > compose.weaviate.yaml << 'EOF'
services:
  weaviate:
    image: semitechnologies/weaviate:latest
    ports:
      - "8085:8080"
      - "50051:50051"
    environment:
      QUERY_DEFAULTS_LIMIT: 25
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: 'true'
      PERSISTENCE_DATA_PATH: '/var/lib/weaviate'
      DEFAULT_VECTORIZER_MODULE: 'none'
      ENABLE_MODULES: ''
      CLUSTER_HOSTNAME: 'node1'
    volumes:
      - weaviate-data:/var/lib/weaviate
    networks:
      - shared-network
    restart: unless-stopped

volumes:
  weaviate-data:

networks:
  shared-network:
    name: shared-network
    driver: bridge
    external: true
EOF

# Start Weaviate
docker-compose -f compose.weaviate.yaml up -d

# Verify Weaviate is running
curl http://localhost:8085/v1/.well-known/ready
# Should return: {"status":"ok"}
```

#### Step 6: Create Environment File

See [Configuration Guide](./atlasml-configuration.md) for detailed explanation of each variable.

```bash
cat > /opt/atlasml/.env << 'EOF'
# API Authentication
ATLAS_API_KEYS='["your-secure-api-key-here"]'

# Weaviate Connection
WEAVIATE_HOST=localhost
WEAVIATE_PORT=8085
WEAVIATE_GRPC_PORT=50051

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

:::warning Security
Never commit the `.env` file to version control. Keep your API keys secure.
:::

#### Step 7: Pull and Start AtlasML

```bash
cd /opt/atlasml

# Pull the image
docker-compose -f compose.atlas.yaml pull

# Start the service
docker-compose -f compose.atlas.yaml up -d

# Check status
docker-compose -f compose.atlas.yaml ps
```

**Expected output**:
```
NAME      IMAGE                                   STATUS    PORTS
atlasml   ghcr.io/ls1intum/edutelligence/atlasml  healthy   0.0.0.0:80->8000/tcp
```

#### Step 8: Verify Installation

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

### Method 2: Manual Docker Run

For simple deployments without docker-compose:

```bash
# Pull image
docker pull ghcr.io/ls1intum/edutelligence/atlasml:main

# Run container
docker run -d \
  --name atlasml \
  --restart unless-stopped \
  -p 80:8000 \
  -e WEAVIATE_HOST=localhost \
  -e WEAVIATE_PORT=8085 \
  -e WEAVIATE_GRPC_PORT=50051 \
  -e ATLAS_API_KEYS='["your-api-key"]' \
  -e OPENAI_API_KEY=your-openai-key \
  -e OPENAI_API_URL=https://your-resource.openai.azure.com \
  -e ENV=production \
  ghcr.io/ls1intum/edutelligence/atlasml:main

# Verify
curl http://localhost/api/v1/health
```

---

### Method 3: Kubernetes (For Large Deployments)

For institutions requiring high availability and auto-scaling:

#### Prerequisites

- Kubernetes cluster (1.20+)
- kubectl configured
- Helm 3.0+

#### Create Namespace

```bash
kubectl create namespace atlasml
```

#### Create Secrets

```bash
# API keys
kubectl create secret generic atlasml-secrets \
  --from-literal=api-keys='["key1","key2"]' \
  --from-literal=openai-key='your-openai-key' \
  -n atlasml
```

#### Create Deployment

```yaml
# atlasml-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: atlasml
  namespace: atlasml
spec:
  replicas: 3
  selector:
    matchLabels:
      app: atlasml
  template:
    metadata:
      labels:
        app: atlasml
    spec:
      containers:
      - name: atlasml
        image: ghcr.io/ls1intum/edutelligence/atlasml:main
        ports:
        - containerPort: 8000
        env:
        - name: WEAVIATE_HOST
          value: "weaviate-service"
        - name: WEAVIATE_PORT
          value: "80"
        - name: ATLAS_API_KEYS
          valueFrom:
            secretKeyRef:
              name: atlasml-secrets
              key: api-keys
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: atlasml-secrets
              key: openai-key
        - name: ENV
          value: "production"
        resources:
          limits:
            memory: "2Gi"
            cpu: "2000m"
          requests:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /api/v1/health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: atlasml-service
  namespace: atlasml
spec:
  selector:
    app: atlasml
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
```

#### Deploy

```bash
kubectl apply -f atlasml-deployment.yaml

# Check status
kubectl get pods -n atlasml
kubectl get svc -n atlasml
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
docker-compose -f compose.atlas.yaml pull

# Restart service (zero downtime if using load balancer)
docker-compose -f compose.atlas.yaml up -d

# Verify
docker logs atlasml
```

### Update to Specific Version

```bash
# Set version in .env
echo "IMAGE_TAG=v1.2.0" >> /opt/atlasml/.env

# Pull and restart
docker-compose -f compose.atlas.yaml pull
docker-compose -f compose.atlas.yaml up -d
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
docker-compose -f compose.atlas.yaml down

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
- **Kubernetes**: https://kubernetes.io/docs/
- **Weaviate Installation**: https://weaviate.io/developers/weaviate/installation
