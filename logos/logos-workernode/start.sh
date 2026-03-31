#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

mode="local"
follow_logs=false
stop_only=false
build_images=false

for arg in "$@"; do
  case "$arg" in
    --gpu) mode="gpu" ;;
    --logs) follow_logs=true ;;
    --stop) stop_only=true ;;
    --build) build_images=true ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

compose_files=(-f docker-compose.yml)
if [[ "$mode" == "gpu" ]]; then
  compose_files+=(-f docker-compose.gpu.yml)
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not accessible for this user." >&2
  exit 1
fi

if $stop_only; then
  docker compose "${compose_files[@]}" down
  exit 0
fi

echo "Starting LogosWorkerNode (mode=$mode)"
if $build_images; then
  docker compose "${compose_files[@]}" up --build -d
else
  docker compose "${compose_files[@]}" up -d
fi

echo "Worker started (WebSocket bridge to Logos server)"
if [[ "$mode" == "gpu" ]]; then
  echo "GPU mode enabled via docker-compose.gpu.yml"
fi
if ! $build_images; then
  echo "Tip: pass --build when Dockerfile/dependencies changed."
fi

if $follow_logs; then
  docker compose "${compose_files[@]}" logs -f
fi
