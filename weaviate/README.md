# Shared Weaviate Instance with Traefik

This directory contains a production-ready Docker Compose setup for a shared Weaviate vector database instance with Traefik as a reverse proxy handling SSL/TLS certificates via Let's Encrypt.

## Overview

This setup provides:
- **Weaviate**: Vector database accessible by Atlas and Iris microservices
- **Traefik**: Reverse proxy with automatic HTTPS via Let's Encrypt
- **Multi2vec-CLIP**: Vector embedding module for Weaviate
- **API Key Authentication**: Secure access control for microservices

## Architecture

```
┌─────────────────┐         ┌─────────────────┐
│     Atlas       │────────▶│                 │
└─────────────────┘         │    Traefik      │
                            │  Port 80/443    │
┌─────────────────┐         │  (REST + HTTPS) │
│     Iris        │────────▶│  Port 50051     │
└─────────────────┘         │  (gRPC + TLS)   │
                            └────────┬────────┘
                                     │
                        ┌────────────┴────────────┐
                        │ HTTPS (REST)            │ gRPC + TLS
                        ▼                         ▼
                ┌─────────────────────────────────────┐
                │            Weaviate                 │◀──┐
                │  REST: 8080    │    gRPC: 50051     │   │
                └─────────────────────────────────────┘   │
                                                          │
                            ┌─────────────────┐           │
                            │ Multi2vec-CLIP  │───────────┘
                            │   (Port 8080)   │
                            └─────────────────┘
```

## Prerequisites

- Docker Engine 20.10+
- Docker Compose v2.0+
- A domain name pointing to your VM's public IP
- Ports 80, 443, and 50051 accessible (80/443 for HTTPS, 50051 for gRPC)

## Quick Start

### 1. Clone and Navigate

```bash
cd edutelligence/weaviate
```

### Available Scripts

This setup includes helper scripts for backup and restore:

- **`backup.sh`**: Creates a backup using Weaviate's backup API
- **`restore.sh`**: Restores from a Weaviate backup

All scripts are located in the `weaviate/` directory and should be run from there.

### 2. Configure Environment Variables

Copy the example environment file and edit it:

```bash
cp .env.example .env
```

⚠️ **SECURITY WARNING**: Never commit the `.env` file to version control! It contains sensitive credentials including your API key. The file is already in `.gitignore`, but always verify before committing.

Edit `.env` and configure the following required variables:

```bash
# Weaviate Domain
WEAVIATE_DOMAIN=weaviate.example.com

# Weaviate Authentication - Generate a secure API key
WEAVIATE_API_KEY=$(openssl rand -base64 32)

# Let's Encrypt Configuration
LETSENCRYPT_EMAIL=your-email@example.com

# IP Whitelisting (Optional)
# Leave empty for public access (default - recommended)
# Set to restrict access: ALLOWED_IPS=10.0.0.0/8,192.168.0.0/16,172.16.0.0/12
ALLOWED_IPS=
```

**Default Security Model**: By default, Weaviate is accessible from any IP address but requires API key authentication. This provides a good balance of security and usability. To add IP-based restrictions, simply set the `ALLOWED_IPS` environment variable in your `.env` file (see Advanced Configuration).

### 3. Generate Secure Credentials

**Weaviate API Key:**
```bash
openssl rand -base64 32
```

Store this key securely - you'll need it for Atlas and Iris configuration.

### 4. Configure DNS

In your DNS provider (e.g., Cloudflare, Route53, etc.), create an A record pointing to your VM's IP address:
- `weaviate.example.com` → Your VM IP

**Important**: Ensure the domain is publicly accessible on ports 80 and 443 before deploying, as Let's Encrypt uses HTTP challenge for certificate validation.

### 5. Create SSL Certificate File

Create the file for Let's Encrypt certificates with proper permissions:

```bash
touch traefik/acme.json
chmod 600 traefik/acme.json
```

### 6. Pre-Deployment Checklist

Before running `docker-compose up -d`, verify:
- [ ] `.env` file exists and is configured (not `.env.example`)
- [ ] `WEAVIATE_API_KEY` is set to a strong random value (not the example)
- [ ] `WEAVIATE_DOMAIN` points to your server's public domain
- [ ] `LETSENCRYPT_EMAIL` is your valid email address
- [ ] `traefik/acme.json` exists with 600 permissions
- [ ] DNS A record is configured and propagated (`nslookup weaviate.example.com`)
- [ ] Firewall allows ports 80, 443 (HTTPS), and 50051 (gRPC) from the internet

### 7. Deploy

```bash
docker-compose up -d
```

### 8. Verify Deployment

Check that all services are running:
```bash
docker-compose ps
```

Check Weaviate health:
```bash
curl -H "Authorization: Bearer YOUR_API_KEY" https://weaviate.example.com/v1/.well-known/ready
```

View logs:
```bash
docker-compose logs -f weaviate
docker-compose logs -f traefik
```

## Configuration Details

### Weaviate Configuration

The Weaviate instance is configured with:
- **API Key Authentication**: Required for all requests
- **Multi2vec-CLIP Module**: Enabled for vector embeddings
- **Persistent Storage**: Data stored in Docker volume `weaviate_data`
- **HTTPS Only**: All HTTP requests redirected to HTTPS

### Traefik Configuration

Traefik is configured to:
- Automatically obtain SSL certificates from Let's Encrypt
- Use HTTP challenge for certificate validation
- Redirect all HTTP traffic to HTTPS
- Auto-renew certificates before expiration

### Security Features

1. **API Key Authentication**: Only requests with valid API keys can access Weaviate
2. **HTTPS Enforcement**: All traffic encrypted with TLS 1.2+ using strong cipher suites
3. **Anonymous Access Disabled**: No unauthenticated access allowed
4. **Internal Network**: Services communicate over private Docker network
5. **Rate Limiting**: 100 requests/second average, 200 burst to prevent abuse
6. **Security Headers**: HSTS, X-Frame-Options, XSS protection enabled
7. **Container Hardening**: No-new-privileges security option on all containers

## Advanced Configuration

### Restricting Access by IP (Optional)

**Default Behavior**: Weaviate is accessible from any IP with valid API key authentication.

**When to use IP restrictions**:
- Restrict to internal networks only (VPN, office IPs)
- Add additional security layer beyond API key auth
- Compliance requirements for network-level access control

**Steps to enable IP whitelisting**:

1. **Edit** `.env` file and set `ALLOWED_IPS` with your IP ranges (comma-separated):
   ```bash
   # Restrict to private networks only
   ALLOWED_IPS=10.0.0.0/8,192.168.0.0/16,172.16.0.0/12

   # Or specific IPs/ranges
   ALLOWED_IPS=203.0.113.1/32,198.51.100.0/24

   # Or single IP
   ALLOWED_IPS=203.0.113.1/32
   ```

2. **Restart** services to apply changes:
   ```bash
   docker-compose up -d
   ```

That's it! The IP whitelist middleware is automatically applied when `ALLOWED_IPS` is set.

**To revert to public access**: Remove or empty the `ALLOWED_IPS` variable in `.env`:
```bash
ALLOWED_IPS=
```

Then restart: `docker-compose up -d`

**How it works**: When `ALLOWED_IPS` is set, Traefik automatically:
- Creates an IP whitelist middleware with your specified IPs
- Applies it to the Weaviate router via Docker labels
- Only allows traffic from the specified IP ranges (in addition to API key auth)

### Adjusting Rate Limits

To modify rate limiting thresholds, edit [`traefik/config.yml`](traefik/config.yml):

```yaml
rate-limit:
  rateLimit:
    average: 100  # Requests per second
    period: 1s
    burst: 200    # Maximum burst size
```

Then restart Traefik: `docker-compose restart traefik`

### Adjusting Resource Limits

Resource limits are now configurable via environment variables in `.env` to match your hardware:

**Default limits** (production-scale):
- **Weaviate**: 8 CPUs, 16GB RAM (limits) / 4 CPUs, 8GB RAM (reservations)
- **Multi2vec-CLIP**: 4 CPUs, 8GB RAM (limits) / 2 CPUs, 4GB RAM (reservations)
- **Traefik**: 1 CPU, 1GB RAM (limits) / 0.5 CPU, 512MB RAM (reservations)

**To adjust**, edit `.env` and set:
```bash
# Weaviate resource limits
WEAVIATE_CPU_LIMIT=8
WEAVIATE_MEMORY_LIMIT=16G
WEAVIATE_CPU_RESERVATION=4
WEAVIATE_MEMORY_RESERVATION=8G

# Multi2vec-CLIP resource limits
CLIP_CPU_LIMIT=4
CLIP_MEMORY_LIMIT=8G
CLIP_CPU_RESERVATION=2
CLIP_MEMORY_RESERVATION=4G

# Traefik resource limits
TRAEFIK_CPU_LIMIT=1
TRAEFIK_MEMORY_LIMIT=1G
TRAEFIK_CPU_RESERVATION=0.5
TRAEFIK_MEMORY_RESERVATION=512M
```

**Hardware sizing recommendations:**

| Setup | Total RAM | Weaviate | CLIP | Notes |
|-------|-----------|----------|------|-------|
| **Small/Dev** | 8GB | 2 CPUs, 4GB | 1 CPU, 2GB | Development only |
| **Medium** | 16GB | 4 CPUs, 8GB | 2 CPUs, 4GB | Small production |
| **Large** | 32GB+ | 8 CPUs, 16GB | 4 CPUs, 8GB | Full production (default) |

**Example for small server (8GB RAM total):**
```bash
WEAVIATE_CPU_LIMIT=2
WEAVIATE_MEMORY_LIMIT=4G
WEAVIATE_CPU_RESERVATION=1
WEAVIATE_MEMORY_RESERVATION=2G

CLIP_CPU_LIMIT=1
CLIP_MEMORY_LIMIT=2G
CLIP_CPU_RESERVATION=1
CLIP_MEMORY_RESERVATION=1G
```

Then restart: `docker-compose up -d`

## Maintenance

### Backup Weaviate Data

**Recommended Method - Using Weaviate Backup API:**

The included `backup.sh` script uses Weaviate's native backup API for consistent backups:

```bash
./backup.sh
```

**What it does:**
1. Reads credentials from `.env` file (uses `WEAVIATE_API_KEY` and `WEAVIATE_DOMAIN`)
2. Initiates a backup via Weaviate's REST API
3. Polls the backup status until completion (max 5 minutes)
4. Copies the backup from the Weaviate container
5. Creates a compressed archive: `./backups/backup-YYYYMMDD-HHMMSS.tar.gz`

**Output:**
```
Starting Weaviate backup: backup-20250115-143022
Backup URL: https://weaviate.example.com

Initiating backup...
Backup initiated successfully

Waiting for backup to complete...
Backup status: TRANSFERRING (attempt 1/60)
Backup completed successfully!

Copying backup from Weaviate container...
Creating compressed archive...

======================================
Backup completed successfully!
Backup ID: backup-20250115-143022
Location: ./backups/backup-20250115-143022.tar.gz
Size: 2.4G
======================================
```

**Features:**
- Uses Weaviate's backup API for consistency (data is safe during backup)
- Creates compressed archives automatically
- Includes status polling and error handling
- Safe for production use (no downtime required)
- Automatic timestamping for easy identification

**Alternative - Volume Backup (Not Recommended):**

For manual volume backups (requires stopping Weaviate):

```bash
# Stop Weaviate
docker-compose stop weaviate

# Backup the volume
docker run --rm -v weaviate_weaviate_data:/data -v $(pwd)/backups:/backup alpine \
  tar czf /backup/volume-backup-$(date +%Y%m%d).tar.gz -C /data .

# Start Weaviate
docker-compose start weaviate
```

### Restore Weaviate Data

**Recommended Method - Using Weaviate Restore API:**

Use the included `restore.sh` script to restore from a Weaviate backup:

```bash
# List available backups
./restore.sh

# Restore a specific backup
./restore.sh backup-20250115-143022
```

**What it does:**
1. Checks if the backup file exists in `./backups/`
2. Prompts for confirmation (shows warning about data replacement)
3. Extracts the backup archive
4. Copies the backup to the Weaviate container
5. Initiates restore via Weaviate's REST API
6. Polls restore status until completion
7. Cleans up temporary files

**Example session:**
```
Available backups:
backup-20250115-143022
backup-20250114-020001

# Run restore
$ ./restore.sh backup-20250115-143022

======================================
WARNING: This will restore Weaviate to the state of backup: backup-20250115-143022
All current data will be replaced!
======================================

Are you sure you want to continue? (yes/no): yes

Extracting backup archive...
Copying backup to Weaviate container...
Initiating restore via Weaviate API...
Restore initiated successfully

Waiting for restore to complete...
Restore status: TRANSFERRING (attempt 1/60)
Restore completed successfully!

======================================
Restore completed successfully!
Backup ID: backup-20250115-143022
======================================
```

**Important notes:**
- ⚠️ **Destructive operation**: All current data in Weaviate will be replaced
- Requires confirmation before proceeding
- Weaviate must be running (does not require downtime)
- Uses Weaviate's API for safe, consistent restore
- Backup file must exist in `./backups/` directory

**Alternative - Volume Restore (Not Recommended):**

For manual volume restores:

```bash
# Stop services
docker-compose down

# Restore from backup
docker run --rm -v weaviate_weaviate_data:/data -v $(pwd)/backups:/backup alpine \
  tar xzf /backup/volume-backup-YYYYMMDD.tar.gz -C /data

# Start services
docker-compose up -d
```

### Backup Best Practices

1. **Schedule Regular Backups**: Set up a cron job to run `backup.sh` regularly:
   ```bash
   # Add to crontab (daily at 2 AM)
   0 2 * * * cd /path/to/weaviate && ./backup.sh >> backup.log 2>&1
   ```

2. **Off-site Storage**: Copy backups to remote storage:
   ```bash
   # Example: Copy to S3
   aws s3 sync ./backups/ s3://your-bucket/weaviate-backups/

   # Example: Copy to another server
   rsync -avz ./backups/ user@backup-server:/backups/weaviate/
   ```

3. **Retention Policy**: Delete old backups to save space:
   ```bash
   # Keep only last 7 days of backups
   find ./backups -name "backup-*.tar.gz" -mtime +7 -delete
   ```

4. **Test Restores**: Periodically test restore procedures to ensure backups work

### Backup/Restore Troubleshooting

**Problem**: `backup.sh` fails with "WEAVIATE_API_KEY not set"

**Solution**: Ensure your `.env` file exists and contains the API key:
```bash
cat .env | grep WEAVIATE_API_KEY
# Should output: WEAVIATE_API_KEY=your-key-here
```

---

**Problem**: Backup times out after 5 minutes

**Solution**: Large datasets may take longer. The script waits up to 5 minutes (60 checks × 5 seconds). To increase:
1. Edit `backup.sh`
2. Change `MAX_RETRIES=60` to a higher value (e.g., `MAX_RETRIES=120` for 10 minutes)

---

**Problem**: "Error: Failed to initiate backup (HTTP 403)"

**Solution**: API key is invalid or doesn't have permission. Verify:
```bash
# Test API key
curl -H "Authorization: Bearer YOUR_API_KEY" https://weaviate.example.com/v1/nodes
```

---

**Problem**: Restore fails with "backup not found"

**Solution**: The backup must exist in Weaviate's backup directory. Check:
```bash
docker exec weaviate ls -la /var/lib/weaviate/backups/filesystem/
```

---

**Problem**: "Cannot connect to weaviate container"

**Solution**: Container must be running. Check status:
```bash
docker ps | grep weaviate
docker-compose ps weaviate
```

---

**Problem**: Backup file is very large

**Solutions**:
- Backups are compressed with gzip (`.tar.gz`)
- Size depends on your data volume
- Consider external storage for large backups (S3, NFS, etc.)
- Implement retention policy to delete old backups

### Update Services

```bash
# Pull latest images
docker-compose pull

# Recreate containers
docker-compose up -d
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f weaviate
docker-compose logs -f traefik
```

## Monitoring

### Log Format

All services log in JSON format to stdout/stderr, making them easy to ingest into logging systems like Grafana Loki.

**Log structure**:
- **Traefik**: JSON access logs with request details, response codes, latency
- **Weaviate**: JSON application logs with structured fields
- **Multi2vec-CLIP**: Standard application logs

### Grafana Integration

Logs are output to stdout in JSON format, compatible with Grafana Loki.

**Example Loki configuration** for Docker logs:
```yaml
scrape_configs:
  - job_name: weaviate
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
    relabel_configs:
      - source_labels: [__meta_docker_container_name]
        regex: /(weaviate|traefik|multi2vec-clip)
        action: keep
      - source_labels: [__meta_docker_container_name]
        target_label: container
```

**Useful Grafana queries**:
```logql
# Traefik access logs with status codes
{container="traefik"} | json | line_format "{{.RequestMethod}} {{.RequestPath}} {{.DownstreamStatus}}"

# Weaviate errors
{container="weaviate"} | json | level="error"

# Request rate
rate({container="traefik"} | json [5m])
```

### Prometheus Metrics (Optional)

To enable Prometheus metrics for monitoring:

1. **Add to** `traefik/traefik.yml`:
   ```yaml
   metrics:
     prometheus:
       addEntryPointsLabels: true
       addServicesLabels: true
   ```

2. **Add to** `docker-compose.yml` Weaviate environment:
   ```yaml
   PROMETHEUS_MONITORING_ENABLED: 'true'
   ```

3. **Expose metrics port** in `docker-compose.yml`:
   ```yaml
   traefik:
     ports:
       - "8082:8082"  # Metrics port
   ```

### Weaviate Health Checks

Check Weaviate cluster status:
```bash
curl -H "Authorization: Bearer YOUR_API_KEY" https://weaviate.example.com/v1/nodes
```

Check schema:
```bash
curl -H "Authorization: Bearer YOUR_API_KEY" https://weaviate.example.com/v1/schema
```

Check readiness (no auth required):
```bash
curl https://weaviate.example.com/v1/.well-known/ready
```

## Troubleshooting

### Certificate Issues

**Problem**: Let's Encrypt certificates not being issued

**Solutions**:
1. Verify DNS records are correct and propagated (use `nslookup weaviate.example.com`)
2. Ensure ports 80 and 443 are accessible from the internet
3. Check firewall rules aren't blocking HTTP challenge
4. Verify email in `.env` is correct
5. Check logs: `docker-compose logs traefik`
6. Delete `traefik/acme.json` and restart: `rm traefik/acme.json && touch traefik/acme.json && chmod 600 traefik/acme.json && docker-compose restart traefik`

### Connection Issues

**Problem**: Cannot connect to Weaviate

**Solutions**:
1. Verify Weaviate is healthy: `docker-compose ps`
2. Check API key is correct
3. Verify DNS resolves to correct IP
4. Check firewall rules allow ports 80 and 443
5. Review logs: `docker-compose logs weaviate`

### Performance Issues

**Problem**: Slow queries or timeouts

**Solutions**:
1. Increase Docker resources (CPU/RAM)
2. Check disk space: `df -h`
3. Review Weaviate logs for errors
4. Monitor with: `docker stats`

### Multi2vec-CLIP Issues

**Problem**: Vector embeddings failing

**Solutions**:
1. Verify multi2vec-clip is running: `docker-compose ps multi2vec-clip`
2. Check logs: `docker-compose logs multi2vec-clip`
3. Restart the service: `docker-compose restart multi2vec-clip`

### Rate Limiting Issues

**Problem**: Getting 429 (Too Many Requests) errors

**Solutions**:
1. Check if you're hitting rate limits (100 req/sec default)
2. Adjust rate limits in [`traefik/config.yml`](traefik/config.yml:22-26)
3. Consider implementing client-side request queuing
4. Check for request loops or excessive polling

### Permission Issues (SELinux/AppArmor)

**Problem**: Volume mount permission denied errors on RHEL/CentOS/Ubuntu

**Solutions for SELinux (RHEL/CentOS)**:
```bash
# Add :z flag to volumes in docker-compose.yml
volumes:
  - ./traefik/acme.json:/acme.json:z
```

**Solutions for AppArmor (Ubuntu)**:
```bash
# Check AppArmor status
sudo aa-status

# If needed, put Docker in complain mode
sudo aa-complain /etc/apparmor.d/docker
```

### Health Check Failures

**Problem**: Services show as unhealthy

**Solutions**:
1. Check service logs: `docker-compose logs [service-name]`
2. Verify health check endpoints manually:
   ```bash
   # Traefik
   docker exec traefik wget -qO- http://localhost:80/ping

   # Weaviate
   docker exec weaviate curl -f -s http://localhost:8080/v1/.well-known/ready

   # Multi2vec-clip
   docker exec multi2vec-clip curl -f -s http://localhost:8080/.well-known/ready
   ```
3. Increase startup time in `docker-compose.yml` if services are slow to start

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WEAVIATE_DOMAIN` | Yes | - | Full domain for Weaviate (e.g., weaviate.example.com) |
| `WEAVIATE_VERSION` | No | 1.30.0 | Weaviate Docker image version |
| `WEAVIATE_API_KEY` | Yes | - | API key for authentication |
| `WEAVIATE_API_USER` | No | admin | Username associated with API key |
| `WEAVIATE_LOG_LEVEL` | No | info | Logging level (trace, debug, info, warning, error, fatal, panic) |
| `LETSENCRYPT_EMAIL` | Yes | - | Email for Let's Encrypt certificate notifications and renewal reminders |
| `ALLOWED_IPS` | No | (empty) | Comma-separated IP ranges for whitelisting (e.g., "10.0.0.0/8,192.168.0.0/16"). Empty = public access with API key auth (recommended) |

## Network Architecture

### External Access
- **Port 80**: HTTP (redirects to HTTPS)
- **Port 443**: HTTPS (Weaviate REST API via Traefik)
- **Port 50051**: gRPC with TLS (Weaviate gRPC API via Traefik - required by Python client v4)

All external traffic (both REST and gRPC) is routed through Traefik with TLS encryption.

### Internal Network
All services communicate over the `weaviate_network` bridge network:
- `traefik` → `weaviate:8080` (HTTP for REST API)
- `traefik` → `weaviate:50051` (gRPC)
- `weaviate` → `multi2vec-clip:8080` (HTTP for embeddings)

## Security Considerations

1. **API Key Storage**: Store the `WEAVIATE_API_KEY` securely and never commit it to version control
2. **Firewall**: Only expose ports 80, 443, and 50051 externally
3. **TLS Everywhere**: Both REST (443) and gRPC (50051) traffic is encrypted via Traefik with Let's Encrypt certificates
4. **Updates**: Regularly update Docker images for security patches
5. **Backups**: Regularly backup the Weaviate data volume
6. **Monitoring**: Monitor logs for suspicious activity

## Support

For issues or questions:
- **Weaviate Documentation**: https://weaviate.io/developers/weaviate
- **Traefik Documentation**: https://doc.traefik.io/traefik/
- **EduTelligence Issues**: https://github.com/ls1intum/edutelligence/issues
