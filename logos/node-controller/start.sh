#!/usr/bin/env bash
# start.sh — build and (re)start the Node Controller.
#
# Usage:
#   ./start.sh           # rebuild + restart
#   ./start.sh --logs    # rebuild + restart + follow logs
#   ./start.sh --stop    # stop everything
#
set -euo pipefail
cd "$(dirname "$0")"

# Bootstrap local env file for first-run convenience.
if [[ ! -f .env && -f .env.example ]]; then
    cp .env.example .env
    echo "Created .env from .env.example"
fi

# Export .env values so startup output reflects actual build flags.
if [[ -f .env ]]; then
    # shellcheck disable=SC1091
    set -a
    source .env
    set +a
fi

# Ensure Docker is usable before any further checks.
if ! docker info >/dev/null 2>&1; then
    echo "Docker daemon is not accessible for this user."
    echo "Run with sudo (for example: sudo ./start.sh) or add your user to the docker group:"
    echo "  sudo usermod -aG docker \$USER"
    echo "  newgrp docker"
    exit 1
fi

# ── Pre-flight checks ────────────────────────────────────────────
has_gpu=false
if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
    has_gpu=true
fi

has_toolkit=false
if docker info 2>/dev/null | grep -qi nvidia; then
    has_toolkit=true
fi

echo "=== Node Controller startup ==="
echo "  GPU detected:              $has_gpu"
echo "  NVIDIA Container Toolkit:  $has_toolkit"
echo "  Build INSTALL_OLLAMA:      ${INSTALL_OLLAMA:-1}"
echo "  Build INSTALL_VLLM:        ${INSTALL_VLLM:-1}"

if $has_gpu && ! $has_toolkit; then
    echo ""
    echo "⚠  GPU found but NVIDIA Container Toolkit is missing."
    echo "   GPU metrics will NOT be available inside Docker."
    echo "   Install it:  sudo apt-get install -y nvidia-container-toolkit && sudo systemctl restart docker"
    echo ""
fi

# ── Handle --stop ─────────────────────────────────────────────────
if [[ "${1:-}" == "--stop" ]]; then
    echo "Stopping node-controller…"
    docker compose down
    echo "Done."
    exit 0
fi

# ── Build & start ─────────────────────────────────────────────────
echo "Rebuilding and starting…"
docker compose down 2>/dev/null || true
docker compose up --build -d

has_vllm=false
if docker exec node-controller sh -lc 'command -v vllm >/dev/null 2>&1'; then
    has_vllm=true
fi

has_ollama=false
if docker exec node-controller sh -lc 'command -v ollama >/dev/null 2>&1'; then
    has_ollama=true
fi

has_cc=false
if docker exec node-controller sh -lc 'command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1 || command -v clang >/dev/null 2>&1'; then
    has_cc=true
fi

has_nvcc=false
if docker exec node-controller sh -lc 'command -v nvcc >/dev/null 2>&1 || test -x /usr/local/cuda-12.8/bin/nvcc || test -x /usr/local/cuda/bin/nvcc'; then
    has_nvcc=true
fi

echo ""
echo "=== Node Controller is up ==="
echo "  Controller:  http://localhost:8444"
echo "  Ollama:      http://localhost:11435"
echo "  Ollama lanes: $has_ollama"
echo "  vLLM lanes:  $has_vllm"
echo "  C compiler:  $has_cc"
echo "  CUDA nvcc:   $has_nvcc"
echo "  Health:      curl http://localhost:8444/health"
if $has_gpu; then
    echo "  GPU metrics: curl -H 'Authorization: Bearer <key>' http://localhost:8444/gpu"
fi
if ! $has_vllm; then
    echo "  Note: vLLM CLI not found in container. Rebuild with INSTALL_VLLM=1."
fi
if ! $has_ollama; then
    echo "  Note: Ollama CLI not found in container. Rebuild with INSTALL_OLLAMA=1."
fi
if $has_vllm && ! $has_cc; then
    echo "  Note: vLLM may fail to start without a C compiler. Rebuild image with INSTALL_VLLM=1."
fi
if $has_vllm && ! $has_nvcc; then
    echo "  Note: vLLM may fail during worker compilation without CUDA nvcc."
fi
echo "  Lane guide:  ./LANES.md"

# ── Optional: follow logs ─────────────────────────────────────────
if [[ "${1:-}" == "--logs" ]]; then
    echo ""
    docker compose logs -f
fi
