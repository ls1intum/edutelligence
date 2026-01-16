#!/usr/bin/env bash
set -euo pipefail

BRANCH="${1:-}"
if [[ -z "$BRANCH" ]]; then
  echo "Usage: $0 <branch-name>"
  exit 1
fi

# ================= CONFIG =================
# Script is run from: edutelligence/logos
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TEST_WORKDIR="$REPO_ROOT/logos/.test-deploy"     # separate git clone (repo root)
TEST_PROJECT="logos_test"

# Test HTTPS ports (must NOT clash with prod 443/8080)
TEST_HTTPS_PORT="18443"
TEST_DASH_PORT="18088"

# For printing URLs; health check uses localhost
TEST_HOST="logos.ase.cit.tum.de"

PROD_DB_CONTAINER="logos-db"
PROD_DB_NAME="logosdb"
PROD_DB_USER="postgres"

COMPOSE_FILE_REL="logos/docker-compose.yaml"
TEST_OVERRIDE="logos/docker-compose.test.yaml"

# Health endpoints
HEALTH_PATH="/"
# ==========================================

cd "$SCRIPT_DIR"

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: missing command: $1"; exit 1; }; }
need_cmd git
need_cmd curl
need_cmd openssl

if [[ ! -f docker-compose.yaml ]]; then
  echo "ERROR: docker-compose.yaml not found in $SCRIPT_DIR"
  exit 1
fi

if ! sudo docker ps --format '{{.Names}}' | grep -qx "$PROD_DB_CONTAINER"; then
  echo "ERROR: PROD DB container '$PROD_DB_CONTAINER' is not running."
  exit 1
fi

# Determine upstream URL from PROD repo (if any) and apply it to test repo origin
PROD_ORIGIN_URL="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)"

echo "==> Test repo root: $TEST_WORKDIR"

if [[ ! -d "$TEST_WORKDIR/.git" ]]; then
  echo "==> Cloning repo root into test workspace..."
  git clone "$REPO_ROOT" "$TEST_WORKDIR"
fi

if [[ -n "$PROD_ORIGIN_URL" ]]; then
  echo "==> Setting test repo origin to PROD upstream: $PROD_ORIGIN_URL"
  git -C "$TEST_WORKDIR" remote set-url origin "$PROD_ORIGIN_URL" 2>/dev/null || \
    git -C "$TEST_WORKDIR" remote add origin "$PROD_ORIGIN_URL"
else
  echo "==> PROD repo has no origin; leaving test origin as-is."
fi

# Add local prod repo as fallback remote (works even if branch isn't pushed)
git -C "$TEST_WORKDIR" remote remove prodsrc >/dev/null 2>&1 || true
git -C "$TEST_WORKDIR" remote add prodsrc "$REPO_ROOT"

echo "==> Fetching refs (origin + prodsrc)"
git -C "$TEST_WORKDIR" fetch origin --prune || true
git -C "$TEST_WORKDIR" fetch prodsrc --prune

echo "==> Checking out branch '$BRANCH' in test repo"
if git -C "$TEST_WORKDIR" show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
  git -C "$TEST_WORKDIR" checkout -B "$BRANCH" "origin/$BRANCH"
elif git -C "$TEST_WORKDIR" show-ref --verify --quiet "refs/remotes/prodsrc/$BRANCH"; then
  git -C "$TEST_WORKDIR" checkout -B "$BRANCH" "prodsrc/$BRANCH"
elif git -C "$TEST_WORKDIR" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git -C "$TEST_WORKDIR" checkout -f "$BRANCH"
else
  echo "ERROR: Branch '$BRANCH' not found in origin or prodsrc."
  echo "Tip (if you intended remote): cd $REPO_ROOT && git push -u origin '$BRANCH'"
  exit 1
fi

git -C "$TEST_WORKDIR" submodule update --init --recursive || true

# --- Generate self-signed cert for test HTTPS ---
CERT_DIR="$TEST_WORKDIR/logos/certs-test"
CERT_KEY="$CERT_DIR/tls.key"
CERT_CRT="$CERT_DIR/tls.crt"
TRAEFIK_TLS_YML="$CERT_DIR/tls.yml"

mkdir -p "$CERT_DIR"

echo "==> Generating self-signed TLS cert for test (CN/SAN: $TEST_HOST)"
# Always regenerate to match hostname changes; you can make this conditional if you want
openssl req -x509 -newkey rsa:2048 -sha256 -days 30 -nodes \
  -keyout "$CERT_KEY" \
  -out "$CERT_CRT" \
  -subj "/CN=$TEST_HOST" \
  -addext "subjectAltName=DNS:$TEST_HOST,DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1

cat > "$TRAEFIK_TLS_YML" <<EOF
tls:
  certificates:
    - certFile: /certs/tls.crt
      keyFile: /certs/tls.key
EOF

echo "==> Writing compose override for test stack (HTTPS on :${TEST_HTTPS_PORT}, self-signed cert)"
mkdir -p "$(dirname "$TEST_WORKDIR/$TEST_OVERRIDE")"

cat > "$TEST_WORKDIR/$TEST_OVERRIDE" <<EOF
services:
  # IMPORTANT:
  # The base compose has a service named 'traefik' that binds 443/8080.
  # We will disable it via: --scale traefik=0
  # and instead run this test-only traefik service with a different name.
  traefik_test:
    image: traefik:v2.10
    container_name: traefik-test
    restart: unless-stopped
    command:
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--providers.file.directory=/certs"
      - "--providers.file.watch=true"

      - "--entrypoints.testwebsecure.address=:${TEST_HTTPS_PORT}"
      - "--entrypoints.testdashboard.address=:${TEST_DASH_PORT}"

      - "--api.dashboard=true"
      - "--log.level=INFO"
    ports:
      - "${TEST_HTTPS_PORT}:${TEST_HTTPS_PORT}"
      - "${TEST_DASH_PORT}:${TEST_DASH_PORT}"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./certs-test:/certs:ro
    networks:
      - internal
      - extern
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.traefik-test-dashboard.rule=PathPrefix(\`/dashboard\`)"
      - "traefik.http.routers.traefik-test-dashboard.entrypoints=testdashboard"
      - "traefik.http.routers.traefik-test-dashboard.service=api@internal"

  logos-server:
    container_name: logos-server-test
    volumes:
      - data_volume_test:/src/logos
    labels:
      - "traefik.enable=true"

      - "traefik.http.routers.logos-server-v1-test.rule=PathPrefix(\`/v1\`)"
      - "traefik.http.routers.logos-server-v1-test.entrypoints=testwebsecure"
      - "traefik.http.routers.logos-server-v1-test.tls=true"
      - "traefik.http.services.logos-server-test-svc.loadbalancer.server.port=8080"

      - "traefik.http.routers.logos-server-logosdb-test.rule=PathPrefix(\`/logosdb\`)"
      - "traefik.http.routers.logos-server-logosdb-test.entrypoints=testwebsecure"
      - "traefik.http.routers.logos-server-logosdb-test.tls=true"
      - "traefik.http.routers.logos-server-logosdb-test.service=logos-server-test-svc"

      - "traefik.http.routers.logos-server-docs-test.rule=PathPrefix(\`/docs\`) || PathPrefix(\`/openapi.json\`)"
      - "traefik.http.routers.logos-server-docs-test.entrypoints=testwebsecure"
      - "traefik.http.routers.logos-server-docs-test.tls=true"
      - "traefik.http.routers.logos-server-docs-test.service=logos-server-test-svc"
    networks:
      - internal

  logos-db:
    container_name: logos-db-test
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: root
      POSTGRES_DB: logosdb
    volumes:
      - ./db/init.sql:/docker-entrypoint-initdb.d/init.sql
      - postgres_data_test:/var/lib/postgresql/data
    networks:
      - internal

  logos-ui:
    container_name: logos-ui-test
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.logos-ui-test.rule=PathPrefix(\`/\`)"
      - "traefik.http.routers.logos-ui-test.entrypoints=testwebsecure"
      - "traefik.http.routers.logos-ui-test.tls=true"
      - "traefik.http.services.logos-ui-test.loadbalancer.server.port=80"
      - "traefik.http.routers.logos-ui-test.priority=1"
    networks:
      - internal

  landing-page:
    container_name: logos-landing-test
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.landing-test.rule=PathPrefix(\`/\`)"
      - "traefik.http.routers.landing-test.entrypoints=testwebsecure"
      - "traefik.http.routers.landing-test.tls=true"
      - "traefik.http.services.landing-test.loadbalancer.server.port=80"
      - "traefik.http.routers.landing-test.priority=0"
    networks:
      - extern

volumes:
  data_volume_test:
  postgres_data_test:
EOF

echo "==> Dumping PROD database"
sudo docker exec -t "$PROD_DB_CONTAINER" \
  pg_dump -U "$PROD_DB_USER" -d "$PROD_DB_NAME" -Fc \
  > "/tmp/${PROD_DB_NAME}_prod.dump"

echo "==> Stopping old test stack (if any)"
sudo docker compose -p "$TEST_PROJECT" \
  -f "$TEST_WORKDIR/$COMPOSE_FILE_REL" \
  -f "$TEST_WORKDIR/$TEST_OVERRIDE" \
  down -v --remove-orphans || true

echo "==> Building test images"
sudo docker compose -p "$TEST_PROJECT" \
  -f "$TEST_WORKDIR/$COMPOSE_FILE_REL" \
  -f "$TEST_WORKDIR/$TEST_OVERRIDE" \
  build

echo "==> Starting test stack (disable inherited prod traefik to avoid 443/8080 bind)"
sudo docker compose -p "$TEST_PROJECT" \
  -f "$TEST_WORKDIR/$COMPOSE_FILE_REL" \
  -f "$TEST_WORKDIR/$TEST_OVERRIDE" \
  up -d --remove-orphans --scale traefik=0

echo "==> Waiting for test DB..."
for i in {1..60}; do
  if sudo docker exec -t logos-db-test pg_isready -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "==> Restoring PROD DB into TEST (1:1)"
cat "/tmp/${PROD_DB_NAME}_prod.dump" | \
  sudo docker exec -i logos-db-test \
  pg_restore -U postgres -d "$PROD_DB_NAME" --clean --if-exists

# ---------------- Health check (HTTPS) ----------------
TEST_URL_LOCAL="https://127.0.0.1:${TEST_HTTPS_PORT}${HEALTH_PATH}"

echo "==> Health check (HTTPS): ${TEST_URL_LOCAL}"
ok=0
for i in {1..45}; do
  # self-signed cert => -k
  if curl -kfsS -o /dev/null "$TEST_URL_LOCAL"; then
    ok=1
    break
  fi
  sleep 2
done

if [[ "$ok" -ne 1 ]]; then
  echo "ERROR: Health check failed for ${TEST_URL_LOCAL}"
  echo
  echo "Recent logs (traefik-test):"
  sudo docker logs --tail 250 traefik-test || true
  echo
  echo "Compose ps:"
  sudo docker compose -p "$TEST_PROJECT" \
    -f "$TEST_WORKDIR/$COMPOSE_FILE_REL" \
    -f "$TEST_WORKDIR/$TEST_OVERRIDE" \
    ps || true
  exit 1
fi

echo "✅ Health check passed: ${TEST_URL_LOCAL}"
# -----------------------------------------------------

echo
echo "✅ Test deployment ready"
echo "   Branch:      $BRANCH"
echo "   Test URL:    https://${TEST_HOST}:${TEST_HTTPS_PORT}/  (self-signed cert; browser warning until trusted)"
echo "   Dashboard:   http://${TEST_HOST}:${TEST_DASH_PORT}/dashboard"
echo
echo "Commands:"
echo "  Logs:"
echo "    sudo docker compose -p $TEST_PROJECT \\"
echo "      -f $TEST_WORKDIR/$COMPOSE_FILE_REL \\"
echo "      -f $TEST_WORKDIR/$TEST_OVERRIDE logs -f"
echo
echo "  Stop:"
echo "    sudo docker compose -p $TEST_PROJECT \\"
echo "      -f $TEST_WORKDIR/$COMPOSE_FILE_REL \\"
echo "      -f $TEST_WORKDIR/$TEST_OVERRIDE down -v"