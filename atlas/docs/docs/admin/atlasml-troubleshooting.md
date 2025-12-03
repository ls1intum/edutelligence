---
title: "AtlasML Troubleshooting"
description: "Common production issues and solutions for AtlasML administrators"
sidebar_position: 6
---

# AtlasML Troubleshooting

This guide covers common production issues encountered by AtlasML administrators and how to resolve them.

---

## Service Health Issues

### Container Won't Start

**Symptom**:
```bash
docker ps
# atlasml is not listed
```

**Diagnosis**:
```bash
# Check logs
docker logs atlasml

# Check exit code
docker inspect atlasml | jq '.[0].State.ExitCode'

# View last run time
docker inspect atlasml | jq '.[0].State.StartedAt'
```

**Common Causes & Solutions**:

#### 1. Missing Environment Variables

**Error in logs**:
```
KeyError: 'ATLAS_API_KEYS'
```

**Solution**:
```bash
# Check .env file exists
ls -la /opt/atlasml/.env

# Verify required variables
cat /opt/atlasml/.env | grep -E "(ATLAS_API_KEYS|WEAVIATE_HOST|WEAVIATE_PORT)"

# If missing, add them
nano /opt/atlasml/.env
```

#### 2. Weaviate Not Running

**Error in logs**:
```
WeaviateConnectionError: Could not connect to Weaviate
```

**Solution**:
```bash
# Check if Weaviate is accessible
curl -H "Authorization: Bearer YOUR_WEAVIATE_API_KEY" https://your-weaviate-domain.com/v1/.well-known/ready
# Should return: {"status":"ok"}

# If Weaviate is not accessible, check the centralized Weaviate service
# (Weaviate runs on a separate server - see /weaviate directory)

# Restart AtlasML
docker-compose -f docker-compose.prod.yml restart atlasml
```

#### 3. Port Already in Use

**Error in logs**:
```
ERROR: bind: address already in use: 0.0.0.0:80
```

**Solution**:
```bash
# Find process using port 80
sudo lsof -i :80
# or
sudo netstat -tulpn | grep :80

# Stop conflicting service
sudo systemctl stop nginx  # or apache2

# Or change AtlasML port in compose file
# Edit docker-compose.prod.yml:
#   ports:
#     - '8080:8000'  # Use 8080 instead of 80
```

#### 4. Image Pull Failed

**Error**:
```
Error response from daemon: pull access denied for ghcr.io/ls1intum/edutelligence/atlasml
```

**Solution**:
```bash
# Login to GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin

# Pull image manually
docker pull ghcr.io/ls1intum/edutelligence/atlasml:main

# Restart
docker-compose -f docker-compose.prod.yml up -d
```

---

### Container Starts But Unhealthy

**Symptom**:
```bash
docker ps
# STATUS: Up 2 minutes (unhealthy)
```

**Diagnosis**:
```bash
# Check health status
docker inspect atlasml | jq '.[0].State.Health'

# View health check logs
docker inspect atlasml | jq '.[0].State.Health.Log'

# Test health endpoint manually
curl http://localhost/api/v1/health
```

**Solutions**:

#### 1. Health Check Timeout

**If health check takes >10s**, increase timeout:

```yaml
# docker-compose.prod.yml
healthcheck:
  timeout: 30s  # Increase from 10s
```

#### 2. Application Not Ready

**If application is slow to start**, increase `start_period`:

```yaml
healthcheck:
  start_period: 30s  # Increase from 10s
```

#### 3. Weaviate Connectivity

**Test from container**:
```bash
docker exec atlasml curl http://${WEAVIATE_HOST}:${WEAVIATE_PORT}/v1/.well-known/ready
```

If fails, check network connectivity and Weaviate status.

---

## Connection Issues

### Weaviate Connection Failed

**Symptom**:
```
WeaviateConnectionError: Could not connect to Weaviate at https://your-weaviate-domain.com
```

**Diagnosis**:
```bash
# 1. Check if Weaviate is accessible
curl -H "Authorization: Bearer YOUR_WEAVIATE_API_KEY" https://your-weaviate-domain.com/v1/.well-known/ready

# 2. Check Weaviate service status on Weaviate server
# SSH to the Weaviate server and check:
docker ps | grep weaviate
docker logs weaviate

# 3. Test from AtlasML container
docker exec atlasml curl -H "Authorization: Bearer ${WEAVIATE_API_KEY}" ${WEAVIATE_HOST}/v1/.well-known/ready

# 4. Check network
docker network inspect shared-network
```

**Solutions**:

#### If Weaviate Not Accessible

```bash
# Check DNS resolution
nslookup your-weaviate-domain.com

# Check if Weaviate server is reachable
ping your-weaviate-domain.com

# Verify Weaviate API key is correct in .env
cat /opt/atlasml/.env | grep WEAVIATE_API_KEY

# Restart AtlasML with updated configuration
docker-compose -f docker-compose.prod.yml restart
```

#### If Weaviate Server Down

SSH to the Weaviate server and check the service:

```bash
# Check Weaviate status
cd /path/to/edutelligence/weaviate
docker-compose ps

# View Weaviate logs
docker-compose logs weaviate

# Restart if needed
docker-compose restart weaviate

# Verify it's accessible
curl -H "Authorization: Bearer YOUR_API_KEY" https://your-weaviate-domain.com/v1/.well-known/ready
```

#### If Host Resolution Issue

```bash
# Check WEAVIATE_HOST value
docker exec atlasml printenv WEAVIATE_HOST

# If using service name, ensure on same Docker network
# If using localhost from container, use host.docker.internal

# Update .env
WEAVIATE_HOST=host.docker.internal
```

---

### OpenAI API Connection Failed

**Symptom**:
```
OpenAI API Error: Authentication failed
```

**Diagnosis**:
```bash
# 1. Check API key is set
docker exec atlasml printenv OPENAI_API_KEY

# 2. Test API directly
curl https://${OPENAI_API_URL}/openai/deployments \
  -H "api-key: ${OPENAI_API_KEY}"
```

**Solutions**:

#### Invalid API Key

```bash
# Verify key in Azure Portal
# Azure Portal → Azure OpenAI → Keys and Endpoint

# Update .env
OPENAI_API_KEY=correct-key-from-azure

# Restart
docker-compose -f docker-compose.prod.yml restart atlasml
```

#### Wrong URL

```bash
# Verify endpoint in Azure Portal
# Should be: https://{resource-name}.openai.azure.com

# Update .env
OPENAI_API_URL=https://correct-resource.openai.azure.com

# Restart
docker-compose -f docker-compose.prod.yml restart atlasml
```

#### Network/Firewall Block

```bash
# Test connectivity from server
curl -I https://your-resource.openai.azure.com

# If blocked, configure firewall to allow HTTPS to *.openai.azure.com
```

---

## API Errors

### 401 Unauthorized

**Symptom**:
```bash
curl http://localhost/api/v1/competency/suggest
# {"detail":"Invalid API key"}
```

**Diagnosis**:
```bash
# 1. Check API keys configured
docker exec atlasml printenv ATLAS_API_KEYS

# 2. Verify format (must be JSON array)
echo $ATLAS_API_KEYS
# Should be: ["key1","key2"]
```

**Solutions**:

#### Missing Authorization Header

```bash
# ❌ Bad - No header
curl http://localhost/api/v1/competency/suggest

# ✅ Good - With Authorization header
curl -H "Authorization: your-api-key" http://localhost/api/v1/competency/suggest
```

#### Wrong Key Format in .env

```bash
# ❌ Bad - Not valid JSON
ATLAS_API_KEYS=[key1,key2]          # Missing quotes
ATLAS_API_KEYS=["key1", "key2"]     # Extra spaces
ATLAS_API_KEYS="[\"key1\"]"         # Escaped quotes

# ✅ Good - Valid JSON array
ATLAS_API_KEYS='["key1","key2"]'

# Fix and restart
docker-compose -f docker-compose.prod.yml restart atlasml
```

#### Key Mismatch

```bash
# Verify Artemis is using correct key
# Check Artemis configuration: application-prod.yml
# atlas.atlasml.api-key should match one of ATLAS_API_KEYS

# Update either AtlasML or Artemis to match
```

---

### 422 Unprocessable Entity

**Symptom**:
```json
{
  "detail": [
    {
      "loc": ["body", "course_id"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

**Cause**: Request body doesn't match expected schema

**Solution**:

```bash
# View API documentation
open http://localhost/docs

# Fix request to include all required fields
curl -X POST http://localhost/api/v1/competency/suggest \
  -H "Authorization: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Python programming",
    "course_id": 1
  }'
```

---

### 500 Internal Server Error

**Symptom**:
```json
{"detail":"Internal server error"}
```

**Diagnosis**:
```bash
# Check application logs
docker logs atlasml --tail 100

# Look for stack traces
docker logs atlasml 2>&1 | grep -A 20 "ERROR"

# Check Sentry (if configured)
# Visit Sentry dashboard for detailed error info
```

**Common Causes**:

#### Database Error

```bash
# Check Weaviate connectivity
docker exec atlasml curl http://${WEAVIATE_HOST}:${WEAVIATE_PORT}/v1/.well-known/ready

# Check Weaviate logs
docker logs weaviate
```

#### OpenAI API Error

```bash
# Check OpenAI quota
# Azure Portal → Azure OpenAI → Usage

# Check rate limits
# If exceeded, wait or upgrade plan
```

#### Memory Issue

```bash
# Check memory usage
docker stats atlasml

# If near limit, increase memory
```

---

## Performance Issues

### Slow Response Times

**Symptom**: Requests take >5 seconds

**Diagnosis**:
```bash
# Measure response time
time curl -X POST http://localhost/api/v1/competency/suggest \
  -H "Authorization: test" \
  -H "Content-Type: application/json" \
  -d '{"description":"test","course_id":1}'

# Check resource usage
docker stats atlasml
```

**Solutions**:

#### High CPU Usage

```bash
# Check CPU
docker stats atlasml --no-stream

# If consistently >80%, scale up:
# Option 1: Increase CPU limit
# docker-compose.prod.yml:
#   deploy:
#     resources:
#       limits:
#         cpus: '4.0'  # Increase from 2.0

# Option 2: Scale horizontally (multiple instances)
docker-compose -f docker-compose.prod.yml up -d --scale atlasml=3
```

#### High Memory Usage

```bash
# Check memory
docker stats atlasml --no-stream

# If near limit, increase memory
# docker-compose.prod.yml:
#   deploy:
#     resources:
#       limits:
#         memory: 4G  # Increase from 2G
```

#### Large Weaviate Collection

```bash
# Check collection size
docker exec weaviate curl http://localhost:8080/v1/schema

# If very large (>100k objects), consider:
# 1. Archiving old data
# 2. Filtering queries by course_id
# 3. Optimizing Weaviate configuration
```

#### OpenAI API Latency

```bash
# Benchmark OpenAI API
time curl https://${OPENAI_API_URL}/openai/deployments/... \
  -H "api-key: ${OPENAI_API_KEY}"

# If slow, check:
# 1. API region (use closest region)
# 2. Rate limiting
# 3. Consider local embeddings for non-critical queries
```

---

### High Memory Usage

**Symptom**:
```
docker stats atlasml
# MEM USAGE: 1.8GB / 2GB (90%)
```

**Diagnosis**:
```bash
# Monitor over time
docker stats atlasml --no-stream

# Check for memory leaks (if usage grows continuously)
# Run for 1 hour and compare
```

**Solutions**:

#### Increase Memory Limit

```yaml
# docker-compose.prod.yml
deploy:
  resources:
    limits:
      memory: 4G  # Increase from 2G
```

#### Optimize Application

```bash
# Check if caching too much data
# Review recent code changes
# Look for memory leaks in logs

# Restart to clear memory (temporary fix)
docker-compose -f docker-compose.prod.yml restart atlasml
```

#### Add Memory Monitoring

```bash
# Set up alert when memory >80%
# See Monitoring Guide for details
```

---

## Deployment Issues

### New Version Not Deploying

**Symptom**: Container running but still old version

**Diagnosis**:
```bash
# Check image tag
docker inspect atlasml | jq '.[0].Config.Image'

# Check when image was pulled
docker inspect atlasml | jq '.[0].Created'

# Check available images
docker images | grep atlasml
```

**Solutions**:

#### Force Pull New Image

```bash
# Pull latest
docker-compose -f docker-compose.prod.yml pull

# Stop and remove container
docker-compose -f docker-compose.prod.yml down

# Start with new image
docker-compose -f docker-compose.prod.yml up -d

# Verify new version
docker logs atlasml | grep "Started"
```

#### Clear Image Cache

```bash
# Remove old images
docker rmi ghcr.io/ls1intum/edutelligence/atlasml:old-tag

# Pull specific version
IMAGE_TAG=v1.2.0 docker-compose -f docker-compose.prod.yml pull

# Restart
IMAGE_TAG=v1.2.0 docker-compose -f docker-compose.prod.yml up -d
```

---

### Deployment Rollback Needed

**Scenario**: New version has critical bug

**Quick Rollback**:
```bash
cd /opt/atlasml

# Set previous version
echo "IMAGE_TAG=v1.1.0" > .env.temp
cat .env >> .env.temp
mv .env.temp .env

# Pull and restart
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d

# Verify
docker logs atlasml
curl http://localhost/api/v1/health
```

---

## Data Issues

### Weaviate Data Lost

**Symptom**: All competencies missing after restart

**Diagnosis**:
```bash
# Check volume exists
docker volume ls | grep weaviate

# Inspect volume
docker volume inspect weaviate-data

# Check mount point
docker inspect weaviate | jq '.[0].Mounts'
```

**Solutions**:

#### Volume Not Mounted

```yaml
# compose.weaviate.yaml
# Ensure volume is configured:
services:
  weaviate:
    volumes:
      - weaviate-data:/var/lib/weaviate  # Mount volume

volumes:
  weaviate-data:  # Declare volume
```

#### Volume Deleted

```bash
# Check if backup exists
ls -lh /path/to/backups/weaviate-*.tar.gz

# Restore from backup
docker-compose -f compose.weaviate.yaml down
sudo tar -xzf weaviate-backup-20250115.tar.gz -C /
docker-compose -f compose.weaviate.yaml up -d
```

#### Create Regular Backups

```bash
# Backup script
#!/bin/bash
docker-compose -f compose.weaviate.yaml stop
sudo tar -czf weaviate-backup-$(date +%Y%m%d).tar.gz \
  /var/lib/docker/volumes/weaviate-data
docker-compose -f compose.weaviate.yaml start

# Run daily via cron
0 2 * * * /opt/atlasml/backup-weaviate.sh
```

---

## Network Issues

### AtlasML Not Reachable from Artemis

**Symptom**: Artemis cannot connect to AtlasML

**Diagnosis**:
```bash
# Test from Artemis server
curl http://atlasml-server:80/api/v1/health

# Check firewall
sudo ufw status
```

**Solutions**:

#### Firewall Blocking

```bash
# Allow from Artemis server
sudo ufw allow from ARTEMIS_IP to any port 80

# Or allow all (less secure)
sudo ufw allow 80/tcp

# Verify
sudo ufw status numbered
```

#### Wrong Hostname/IP in Artemis

```yaml
# application-prod.yml in Artemis
atlas:
  atlasml:
    base-url: https://correct-hostname-or-ip  # Fix this
    api-key: your-api-key
```

#### DNS Issue

```bash
# Test DNS resolution from Artemis
nslookup atlasml-server.company.com

# If fails, add to /etc/hosts
echo "192.168.1.100 atlasml-server" | sudo tee -a /etc/hosts
```

---

### SSL/TLS Certificate Issues

**Symptom**: HTTPS connection fails

**Diagnosis**:
```bash
# Test SSL
curl -v https://atlasml.company.com/api/v1/health

# Check certificate
openssl s_client -connect atlasml.company.com:443 -servername atlasml.company.com
```

**Solutions**:

#### Certificate Expired

```bash
# Renew Let's Encrypt certificate
sudo certbot renew

# Reload Nginx
sudo systemctl reload nginx
```

#### Self-Signed Certificate

```bash
# If using self-signed, Artemis must trust it
# Copy cert to Artemis server
scp /etc/ssl/certs/atlasml.crt artemis-server:/usr/local/share/ca-certificates/
ssh artemis-server 'sudo update-ca-certificates'
```

---

## Troubleshooting Checklist

When encountering an issue:

1. **Check service health**
   ```bash
   docker ps
   docker logs atlasml --tail 50
   ```

2. **Test connectivity**
   ```bash
   curl http://localhost/api/v1/health
   curl http://localhost:8085/v1/.well-known/ready
   ```

3. **Verify configuration**
   ```bash
   docker exec atlasml env | grep -E "(WEAVIATE|OPENAI|ATLAS)"
   ```

4. **Check resources**
   ```bash
   docker stats atlasml --no-stream
   df -h
   ```

5. **Review logs**
   ```bash
   docker logs atlasml 2>&1 | grep ERROR
   docker logs weaviate 2>&1 | grep ERROR
   ```

6. **Check Sentry** (if configured)
   - Visit Sentry dashboard
   - Filter by environment and time

---

## Getting Help

### Gather Information

Before reporting issues, collect:

```bash
# System info
uname -a
docker --version
docker-compose --version

# Container status
docker ps -a | grep atlasml

# Recent logs
docker logs atlasml --tail 100 > atlasml-logs.txt

# Configuration (mask secrets!)
docker exec atlasml env | grep -E "(WEAVIATE|ATLAS|ENV)" | sed 's/=.*/=***/' > config.txt

# Resource usage
docker stats atlasml --no-stream > stats.txt
```

### Report Issue

Include in report:
1. **Description**: What were you trying to do?
2. **Expected**: What should happen?
3. **Actual**: What actually happened?
4. **Environment**:
   - OS and version
   - Docker version
   - AtlasML version/image tag
5. **Logs**: Relevant error messages
6. **Steps to reproduce**: How to recreate the issue

---

## Common Error Messages

| Error | Cause | Solution |
|-------|-------|----------|
| `WeaviateConnectionError` | Weaviate not running | Start Weaviate |
| `401 Unauthorized` | Invalid/missing API key | Check Authorization header |
| `422 Unprocessable Entity` | Invalid request body | Check request schema |
| `500 Internal Server Error` | Server-side error | Check logs |
| `Connection refused` | Service not running | Start service |
| `Address already in use` | Port conflict | Change port or stop other service |
| `No such container` | Container not running | Start container |
| `pull access denied` | Image not accessible | Check credentials |

---

## Next Steps

- **[Installation](./atlasml-installation.md)**: Reinstall if needed
- **[Configuration](./atlasml-configuration.md)**: Verify configuration
- **[Monitoring](./atlasml-monitoring.md)**: Set up monitoring to catch issues early
- **[Deployment](./atlasml-deployment.md)**: Review deployment process

---

## Resources

- **Docker Troubleshooting**: https://docs.docker.com/config/daemon/troubleshoot/
- **Weaviate Troubleshooting**: https://weaviate.io/developers/weaviate/installation/troubleshooting
- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **GitHub Issues**: https://github.com/ls1intum/edutelligence/issues
