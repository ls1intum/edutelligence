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
└─────────────────┘         │                 │
                            │    Traefik      │
┌─────────────────┐         │  (Port 80/443)  │
│     Iris        │────────▶│                 │
└─────────────────┘         │                 │
                            └────────┬────────┘
                                     │ HTTPS
                                     ▼
                            ┌─────────────────┐
                            │    Weaviate     │◀──┐
                            │   (Port 8080)   │   │
                            └─────────────────┘   │
                                                  │
                            ┌─────────────────┐   │
                            │ Multi2vec-CLIP  │───┘
                            │   (Port 8080)   │
                            └─────────────────┘
```

## Prerequisites

- Docker Engine 20.10+
- Docker Compose v2.0+
- A domain name pointing to your VM's public IP
- Ports 80 and 443 accessible from the internet (required for Let's Encrypt HTTP challenge)

## Quick Start

### 1. Clone and Navigate

```bash
cd edutelligence/weaviate
```

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
```

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

### 5. Pre-Deployment Checklist

Before running `docker-compose up -d`, verify:
- [ ] `.env` file exists and is configured (not `.env.example`)
- [ ] `WEAVIATE_API_KEY` is set to a strong random value (not the example)
- [ ] `WEAVIATE_DOMAIN` points to your server's public domain
- [ ] `LETSENCRYPT_EMAIL` is your valid email address
- [ ] `traefik/acme.json` exists with 600 permissions
- [ ] DNS A record is configured and propagated (`nslookup weaviate.example.com`)
- [ ] Firewall allows ports 80 and 443 from the internet

### 6. Deploy

```bash
docker-compose up -d
```

### 7. Verify Deployment

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

## Connecting Microservices

### From Atlas

Update your Atlas configuration to connect to the shared Weaviate instance:

```yaml
weaviate:
  host: "weaviate.example.com"
  port: "443"
  scheme: "https"
  api_key: "your-weaviate-api-key"
```

### From Iris

Update your Iris `application.yml` configuration:

```yaml
weaviate:
  host: "weaviate.example.com"
  port: "443"
  grpc_port: "443"
  scheme: "https"
  api_key: "your-weaviate-api-key"
```

**Note**: If Atlas and Iris are running on the same VM, they can also connect via the internal Docker network using `http://weaviate:8080` instead of going through Traefik.

## Advanced Configuration

### Restricting Access by IP (Optional)

By default, Weaviate is publicly accessible with API key authentication. To restrict access to specific IP ranges (e.g., internal networks only):

1. **Edit** [`docker-compose.yml`](docker-compose.yml:83)
2. **Change** the middleware line from:
   ```yaml
   - "traefik.http.routers.weaviate-secure.middlewares=default-headers,rate-limit"
   ```
   To:
   ```yaml
   - "traefik.http.routers.weaviate-secure.middlewares=secured"
   ```

3. **Update** IP ranges in [`traefik/config.yml`](traefik/config.yml:30-35) if needed:
   ```yaml
   default-whitelist:
     ipAllowList:
       sourceRange:
         - "10.0.0.0/8"          # Your internal network
         - "192.168.0.0/16"
         - "172.16.0.0/12"
         - "YOUR_OFFICE_IP/32"  # Add specific IPs
   ```

4. **Restart** Traefik:
   ```bash
   docker-compose restart traefik
   ```

### Adjusting Rate Limits

To modify rate limiting thresholds, edit [`traefik/config.yml`](traefik/config.yml:22-26):

```yaml
rate-limit:
  rateLimit:
    average: 100  # Requests per second
    period: 1s
    burst: 200    # Maximum burst size
```

Then restart Traefik: `docker-compose restart traefik`

### Adjusting Resource Limits

Default resource limits in [`docker-compose.yml`](docker-compose.yml):
- **Weaviate**: 8 CPUs, 16GB RAM (limits) / 4 CPUs, 8GB RAM (reservations)
- **Multi2vec-CLIP**: 4 CPUs, 8GB RAM (limits) / 2 CPUs, 4GB RAM (reservations)
- **Traefik**: 1 CPU, 1GB RAM (limits) / 0.5 CPU, 512MB RAM (reservations)

Adjust these based on your workload requirements.

## Maintenance

### Backup Weaviate Data

```bash
# Backup the volume
docker run --rm -v weaviate_weaviate_data:/data -v $(pwd)/backup:/backup alpine \
  tar czf /backup/weaviate-backup-$(date +%Y%m%d).tar.gz -C /data .
```

### Restore Weaviate Data

```bash
# Stop services
docker-compose down

# Restore from backup
docker run --rm -v weaviate_weaviate_data:/data -v $(pwd)/backup:/backup alpine \
  tar xzf /backup/weaviate-backup-YYYYMMDD.tar.gz -C /data

# Start services
docker-compose up -d
```

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
   docker exec weaviate wget -qO- http://localhost:8080/v1/.well-known/ready

   # Multi2vec-clip
   docker exec multi2vec-clip wget -qO- http://localhost:8080/.well-known/ready
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

## Network Architecture

### External Access
- **Port 80**: HTTP (redirects to HTTPS)
- **Port 443**: HTTPS (Weaviate API)

### Internal Network
All services communicate over the `weaviate_network` bridge network:
- `traefik` → `weaviate:8080`
- `weaviate` → `multi2vec-clip:8080`

## Security Considerations

1. **API Key Storage**: Store the `WEAVIATE_API_KEY` securely and never commit it to version control
2. **Firewall**: Only expose ports 80 and 443 externally
3. **Updates**: Regularly update Docker images for security patches
4. **Backups**: Regularly backup the Weaviate data volume
5. **Monitoring**: Monitor logs for suspicious activity

## Support

For issues or questions:
- **Weaviate Documentation**: https://weaviate.io/developers/weaviate
- **Traefik Documentation**: https://doc.traefik.io/traefik/
- **EduTelligence Issues**: https://github.com/ls1intum/edutelligence/issues
