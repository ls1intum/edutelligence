---
title: 'nginx Configuration'
---

# nginx Configuration for AtlasML

AtlasML uses nginx as a reverse proxy to handle HTTPS/SSL termination and route traffic to the FastAPI application.

## Configuration File Location

On the production server, the nginx configuration is located at:
```
/opt/atlasml/nginx.conf
```

This file is mounted into the nginx container as a read-only volume.

## nginx Configuration

Create `/opt/atlasml/nginx.conf` with the following content:

```nginx
events {
    worker_connections 1024;
}

http {
    upstream atlasml {
        server atlasml:80;
    }

    # Redirect HTTP to HTTPS
    server {
        listen 80;
        server_name atlasml.aet.cit.tum.de;

        location /health {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }

        location / {
            return 301 https://$host$request_uri;
        }
    }

    # HTTPS server
    server {
        listen 443 ssl http2;
        server_name atlasml.aet.cit.tum.de;

        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;

        # SSL configuration
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;

        # Proxy settings
        location / {
            proxy_pass http://atlasml;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Timeouts
            proxy_connect_timeout 60s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }
    }
}
```

## Configuration Breakdown

### events Block

```nginx
events {
    worker_connections 1024;
}
```

Configures nginx to handle up to 1024 simultaneous connections per worker process.

### upstream Block

```nginx
upstream atlasml {
    server atlasml:80;
}
```

Defines the backend service. `atlasml:80` refers to:
- `atlasml`: Docker service name from compose.atlas.yaml
- `80`: Port the atlasml container listens on internally

### HTTP Server (Port 80)

```nginx
server {
    listen 80;
    server_name atlasml.aet.cit.tum.de;

    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}
```

**Purpose:**
- Provides a `/health` endpoint for monitoring (doesn't hit the backend)
- Redirects all HTTP traffic to HTTPS (301 permanent redirect)

### HTTPS Server (Port 443)

```nginx
server {
    listen 443 ssl http2;
    server_name atlasml.aet.cit.tum.de;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Proxy settings
    location / {
        proxy_pass http://atlasml;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

**SSL Configuration:**
- Uses TLS 1.2 and 1.3 protocols (secure and modern)
- Uses strong cipher suites (HIGH) and excludes weak ones (aNULL, MD5)
- Certificates are mounted from `/opt/atlasml/ssl/` on the host

**Proxy Headers:**
- `Host`: Preserves the original host header
- `X-Real-IP`: Client's real IP address
- `X-Forwarded-For`: Chain of proxy IP addresses
- `X-Forwarded-Proto`: Original protocol (https)

**Timeouts:**
- Connection, send, and read timeouts set to 60 seconds each

## SSL Certificate Setup

nginx requires SSL certificates at:
- `/etc/nginx/ssl/cert.pem` (inside container)
- `/etc/nginx/ssl/key.pem` (inside container)

These are mapped from `/opt/atlasml/ssl/` on the host.

### Option 1: Let's Encrypt (Recommended)

```bash
# Install certbot
sudo apt-get update
sudo apt-get install certbot

# Stop nginx temporarily
cd /opt/atlasml
sudo docker-compose -f compose.atlas.yaml stop nginx

# Generate certificate
sudo certbot certonly --standalone -d atlasml.aet.cit.tum.de

# Copy certificates
sudo mkdir -p /opt/atlasml/ssl
sudo cp /etc/letsencrypt/live/atlasml.aet.cit.tum.de/fullchain.pem /opt/atlasml/ssl/cert.pem
sudo cp /etc/letsencrypt/live/atlasml.aet.cit.tum.de/privkey.pem /opt/atlasml/ssl/key.pem
sudo chmod 644 /opt/atlasml/ssl/cert.pem
sudo chmod 600 /opt/atlasml/ssl/key.pem

# Restart services
sudo docker-compose -f compose.atlas.yaml up -d
```

**Certificate Renewal:**

Let's Encrypt certificates expire after 90 days. Set up automatic renewal:

```bash
# Test renewal
sudo certbot renew --dry-run

# Create renewal hook script
sudo nano /etc/letsencrypt/renewal-hooks/deploy/copy-certs.sh
```

Add to the script:
```bash
#!/bin/bash
cp /etc/letsencrypt/live/atlasml.aet.cit.tum.de/fullchain.pem /opt/atlasml/ssl/cert.pem
cp /etc/letsencrypt/live/atlasml.aet.cit.tum.de/privkey.pem /opt/atlasml/ssl/key.pem
chmod 644 /opt/atlasml/ssl/cert.pem
chmod 600 /opt/atlasml/ssl/key.pem
cd /opt/atlasml && docker-compose -f compose.atlas.yaml restart nginx
```

Make it executable:
```bash
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/copy-certs.sh
```

### Option 2: Self-Signed Certificate (Testing Only)

```bash
sudo mkdir -p /opt/atlasml/ssl
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /opt/atlasml/ssl/key.pem \
  -out /opt/atlasml/ssl/cert.pem \
  -subj "/C=DE/ST=Bavaria/L=Munich/O=TUM/CN=atlasml.aet.cit.tum.de"

sudo chmod 644 /opt/atlasml/ssl/cert.pem
sudo chmod 600 /opt/atlasml/ssl/key.pem
```

**Warning:** Browsers will show security warnings for self-signed certificates.

### Option 3: Organization Certificate

Contact your organization's IT department to obtain:
- SSL certificate for `atlasml.aet.cit.tum.de`
- Private key file

Then copy them to:
```bash
sudo cp your-cert.crt /opt/atlasml/ssl/cert.pem
sudo cp your-key.key /opt/atlasml/ssl/key.pem
sudo chmod 644 /opt/atlasml/ssl/cert.pem
sudo chmod 600 /opt/atlasml/ssl/key.pem
```

## Testing nginx Configuration

### Validate Configuration Syntax

```bash
sudo docker run --rm \
  -v /opt/atlasml/nginx.conf:/etc/nginx/nginx.conf:ro \
  nginx:alpine nginx -t
```

### Test HTTP to HTTPS Redirect

```bash
curl -I http://atlasml.aet.cit.tum.de
```

Expected output:
```
HTTP/1.1 301 Moved Permanently
Location: https://atlasml.aet.cit.tum.de/
```

### Test HTTPS Endpoint

```bash
# With certificate verification
curl https://atlasml.aet.cit.tum.de/api/v1/health

# Ignoring certificate errors (for self-signed certs)
curl -k https://atlasml.aet.cit.tum.de/api/v1/health
```

### Test Health Endpoint

```bash
curl http://localhost/health
```

Expected output:
```
healthy
```

## Customizing the Configuration

### Adding Custom Headers

Add security headers in the HTTPS server block:

```nginx
# Add security headers
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
```

### Increasing Upload Size

If you need to handle large uploads:

```nginx
http {
    client_max_body_size 50M;

    # ... rest of configuration
}
```

### Enabling Gzip Compression

```nginx
http {
    gzip on;
    gzip_types text/plain text/css application/json application/javascript;
    gzip_min_length 1000;

    # ... rest of configuration
}
```

### Custom Logging

```nginx
http {
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log warn;

    # ... rest of configuration
}
```

Mount log directory in compose.atlas.yaml:
```yaml
nginx:
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf:ro
    - ./ssl:/etc/nginx/ssl:ro
    - ./logs:/var/log/nginx
```

## Troubleshooting

### nginx Container Won't Start

Check configuration syntax:
```bash
sudo docker run --rm \
  -v /opt/atlasml/nginx.conf:/etc/nginx/nginx.conf:ro \
  nginx:alpine nginx -t
```

View nginx logs:
```bash
sudo docker logs atlasml-nginx-1
```

### 502 Bad Gateway

This usually means nginx can't reach the backend. Check:

1. Is atlasml container running and healthy?
```bash
sudo docker ps
```

2. Can nginx reach atlasml?
```bash
sudo docker exec atlasml-nginx-1 wget -O- http://atlasml:80/api/v1/health
```

### SSL Certificate Errors

Verify certificate files exist:
```bash
ls -la /opt/atlasml/ssl/
```

Check certificate validity:
```bash
openssl x509 -in /opt/atlasml/ssl/cert.pem -text -noout
```

## See Also

- [Deployment Guide](deployment.md)
- [Server Setup from Scratch](server-setup.md)
- [API Documentation](api.md)
