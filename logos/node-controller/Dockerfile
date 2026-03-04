# ---- build ----
FROM python:3.13-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- runtime ----
FROM python:3.13-slim

# curl is used by the Docker healthcheck and is useful for debugging
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /install /usr/local
COPY node_controller/ /app/node_controller/
RUN mkdir -p /app/certs

EXPOSE 8443

# Runs as root — same as Portainer, Watchtower, and similar Docker-management
# tools.  Docker socket access is equivalent to host root, so a non-root user
# would only break portability (socket GID varies) without adding security.
CMD ["python", "-m", "node_controller.main"]
