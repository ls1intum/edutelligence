# Nebula

This is the central orchestration repository for all Nebula services.

## 🚀 Quick Start for Developers

This guide will help you get the Nebula services running locally for development.

### Prerequisites

- Python 3.12
- Poetry
- Docker Desktop (nginx uses `huynhquangtoan/openresty-lua-resty-http` image)
- Git

### Step 1: Clone and Install Dependencies

```bash
# Clone the repository
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence/nebula

# Install Python dependencies
poetry install

# Copy example configurations
cp llm_config.example.yml llm_config.local.yml
cp nginx.local_example.conf nginx.local.conf
```

### Step 2: Configure LLM Settings

Edit `llm_config.local.yml` with your API keys and endpoints:

```yaml
llms:
  - id: "azure-gpt-4-omni"
    type: "azure_openai"
    api_key: "YOUR_API_KEY" # pragma: allowlist secret
    endpoint: "YOUR_ENDPOINT"
    # ... other settings
```

### Step 3: Start Services Locally

Open **three separate terminals** for the services:

**Terminal 1 - Transcriber Service (Port 3870):**

```bash
cd edutelligence/nebula
poetry run uvicorn nebula.transcript.app:app --host 0.0.0.0 --port 3870 --reload
```

**Terminal 2 - FAQ Service (Port 3871):**

```bash
cd edutelligence/nebula
poetry run uvicorn nebula.faq.app:app --host 0.0.0.0 --port 3871 --reload
```

**Terminal 3 - Nginx Gateway (Port 3007):**

```bash
cd edutelligence/nebula
# Clean up any existing containers first
docker compose -f docker/nginx-only.yml down
docker rm -f nebula-nginx-gateway 2>/dev/null || true

# Start nginx gateway
docker compose -f docker/nginx-only.yml up
```

### Step 4: Verify Everything is Running

```bash
# Check health status (should return JSON with service statuses)
curl http://localhost:3007/health

# Test transcriber endpoint (requires API key)
curl -H "Authorization: nebula-secret" http://localhost:3007/transcribe/test

# Test FAQ endpoint (requires API key)
curl -H "Authorization: nebula-secret" http://localhost:3007/faq/test
```

### Development Workflow

1. **Services run locally with hot reload** - Any changes to Python files automatically restart the service
2. **Nginx provides API gateway** - Handles authentication, routing, and health checks
3. **Access all services through port 3007** - Single entry point for all APIs

### Troubleshooting

- **Port already in use**: Make sure ports 3870, 3871, and 3007 are free
- **Connection refused**: Ensure all services are running
- **Unauthorized errors**: Check the API key in nginx.local.conf matches what you're sending
- **Module not found**: Run `poetry install` to ensure all dependencies are installed
- **Nginx container exits immediately**:
  - Remove old containers: `docker rm -f nebula-nginx-gateway`
  - Check logs: `docker compose -f docker/nginx-only.yml logs`
  - Ensure nginx.local.conf exists and has correct syntax
- **"host not found in upstream" errors**: Your nginx.local.conf might be outdated. Copy the latest example:
  ```bash
  cp nginx.local_example.conf nginx.local.conf
  ```

## 🚢 Production Deployment

This guide covers deploying Nebula services in a production environment.

### Prerequisites

- Docker and Docker Compose installed on the server
- SSL certificates for HTTPS
- Domain name configured with DNS pointing to your server
- Access to container registry (GitHub Container Registry)

### Step 1: Prepare Configuration Files

```bash
# Clone the repository on your production server
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence/nebula

# Copy and configure production files
cp .env.production-example .env
cp nginx.compose_example.conf nginx.production.conf
cp llm_config.example.yml llm_config.production.yml

# Edit the .env file with your production values
nano .env
# Update these key variables:
# - NEBULA_SSL_CERT and NEBULA_SSL_KEY with your SSL certificate paths
# - NEBULA_NGINX_CONFIG_FILE=./nginx.production.conf
# - NEBULA_LLM_CONFIG_FILE=./llm_config.production.yml
# - NEBULA_TEMP_DIR with your desired temp directory
```

### Step 2: Configure Nginx for Production

Edit `nginx.production.conf`:

```nginx
# Update API key (line ~26)
"your-production-api-key" 1;  # CHANGE THIS

# Update server name (line ~50)
server_name api.yourdomain.com;  # CHANGE THIS

# Enable HTTPS (uncomment lines ~54, ~61-62)
listen 443 ssl http2;
ssl_certificate /path/to/your/certificate.crt;
ssl_certificate_key /path/to/your/private.key;

# Optional: Enable HTTPS redirect (uncomment lines ~78-80)
if ($scheme = http) {
    return 301 https://$server_name$request_uri;
}
```

### Step 3: Configure LLM Settings

Edit `llm_config.production.yml` with your production API credentials:

```yaml
llms:
  - id: "azure-gpt-4-omni"
    type: "azure_openai"
    api_key: "${AZURE_API_KEY}" # Can use environment variables # pragma: allowlist secret
    endpoint: "${AZURE_ENDPOINT}"
    api_version: "2024-02-15-preview"
    deployment: "gpt-4-omni"
```

### Step 4: Deploy with Docker Compose

```bash
# Pull latest images (if using pre-built images)
docker compose -f docker/nebula-production.yml pull

# Or build locally
docker compose -f docker/nebula-production.yml build

# Start all services
docker compose -f docker/nebula-production.yml up -d

# Check logs
docker compose -f docker/nebula-production.yml logs -f

# Verify deployment
curl https://api.yourdomain.com/health
```

### Step 5: Set Up SSL/TLS (Using Let's Encrypt)

For automatic SSL with Let's Encrypt, you can use Certbot:

```bash
# Install Certbot
apt-get update
apt-get install certbot

# Get certificates
certbot certonly --standalone -d api.yourdomain.com

# Update nginx.production.conf with cert paths
ssl_certificate /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/api.yourdomain.com/privkey.pem;

# Restart nginx
docker compose -f docker/nebula-production.yml restart nginx
```

### Production Monitoring

#### Health Checks

```bash
# Check overall system health
curl https://api.yourdomain.com/health

# Monitor logs
docker compose -f docker/nebula-production.yml logs -f

# Check individual service logs
docker logs transcriber-service
docker logs faq-service
docker logs nginx-proxy
```

#### Service Management

```bash
# Stop services
docker compose -f docker/nebula-production.yml down

# Restart services
docker compose -f docker/nebula-production.yml restart

# Update services
docker compose -f docker/nebula-production.yml pull
docker compose -f docker/nebula-production.yml up -d

# Scale services (if needed)
docker compose -f docker/nebula-production.yml up -d --scale transcriber=2
```

### Security Considerations

1. **API Keys**: Use strong, unique API keys in production
2. **HTTPS**: Always use HTTPS in production with valid SSL certificates
3. **Firewall**: Configure firewall to only allow ports 80, 443
4. **Updates**: Regularly update Docker images and dependencies
5. **Secrets**: Use environment variables or secret management for sensitive data
6. **Rate Limiting**: Consider adding rate limiting in nginx configuration
7. **Monitoring**: Set up monitoring and alerting for service health

### Backup and Recovery

```bash
# Backup configuration files
tar -czf nebula-config-backup.tar.gz \
  nginx.production.conf \
  llm_config.production.yml \
  .env

# Backup any persistent data
docker compose -f docker/nebula-production.yml exec transcriber \
  tar -czf /backup/transcriber-data.tar.gz /app/temp

# Restore from backup
tar -xzf nebula-config-backup.tar.gz
docker compose -f docker/nebula-production.yml up -d
```

### Troubleshooting Production Issues

- **Services not starting**: Check Docker logs with `docker compose logs`
- **SSL errors**: Verify certificate paths and permissions
- **502 Bad Gateway**: Check if backend services are running and healthy
- **Out of memory**: Monitor with `docker stats` and adjust container limits
- **Disk space**: Check with `df -h` and clean up old Docker images/containers
