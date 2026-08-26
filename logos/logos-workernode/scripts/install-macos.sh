#!/usr/bin/env bash
# =============================================================================
# Logos Worker Node — native macOS installer (Apple Silicon / MLX)
#
# Idempotent: safe to re-run on every deploy. Creates two separate virtualenvs
# and does NOT merge them:
#
#   ~/.venv-vllm-metal   vLLM + vllm-metal + MLX. Created by vllm-metal's own
#                        install.sh, which pins a combination of vllm, mlx and
#                        torch that is known to work together. The lanes run
#                        from here.
#   <home>/.venv         The worker itself (fastapi/uvicorn/httpx/pydantic).
#                        Kept separate so a vllm-metal upgrade cannot drag the
#                        worker's dependencies along, and so the worker starts
#                        even while the much larger ML venv is being rebuilt.
#
# Usage: ./install-macos.sh [install-root]
# =============================================================================
set -euo pipefail

INSTALL_ROOT="${1:-${LOGOS_MLX_HOME:-$HOME/logos-workernode-mlx}}"
METAL_VENV="${LOGOS_METAL_VENV:-$HOME/.venv-vllm-metal}"
VLLM_METAL_INSTALLER="https://raw.githubusercontent.com/vllm-project/vllm-metal/main/install.sh"

log()  { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; exit 1; }

# ── Preflight ────────────────────────────────────────────────────────────────
[ "$(uname -s)" = "Darwin" ] || die "This installer is macOS-only (found $(uname -s)).
The Metal backend needs direct GPU access, which exists only on a real Mac —
not in a Linux container. Use the CUDA image for Linux GPU nodes."

[ "$(uname -m)" = "arm64" ] || die "Apple Silicon required (found $(uname -m)).
An x86_64/Rosetta Python cannot load MLX."

macos_major="$(sw_vers -productVersion | cut -d. -f1)"
if [ "$macos_major" -lt 15 ]; then
    die "macOS 15 (Sequoia) or later required — found $(sw_vers -productVersion)."
fi

log "Install root:      $INSTALL_ROOT"
log "vllm-metal venv:   $METAL_VENV"

# ── 1. vllm-metal virtualenv ─────────────────────────────────────────────────
# Deliberately delegated to upstream's installer rather than pinning versions
# here: vllm-metal ships a matched (vllm, mlx, torch) set, and picking those
# apart in our own requirements file is how you get an unbootable lane.
if [ -x "$METAL_VENV/bin/vllm" ]; then
    installed_version="$("$METAL_VENV/bin/python" -c \
        'import importlib.metadata as m; print(m.version("vllm-metal"))' 2>/dev/null || echo unknown)"
    log "vllm-metal already present (version $installed_version) — skipping"
else
    log "Installing vllm-metal into $METAL_VENV (this downloads several GB)…"
    curl -fsSL "$VLLM_METAL_INSTALLER" | bash
    [ -x "$METAL_VENV/bin/vllm" ] || die "vllm-metal install finished but $METAL_VENV/bin/vllm is missing."
fi

# Fail loudly here rather than at first lane spawn: an importable plugin is the
# single thing that distinguishes a working node from one that silently serves
# every request on the CPU.
log "Verifying the Metal platform plugin loads…"
"$METAL_VENV/bin/python" - <<'PYCHECK' || die "vllm-metal is installed but the Metal plugin does not load."
import sys
try:
    import mlx.core as mx
    import vllm_metal  # noqa: F401
except Exception as exc:
    print(f"  plugin import failed: {exc}", file=sys.stderr)
    sys.exit(1)
info = mx.device_info()
budget = info.get("max_recommended_working_set_size", 0) / 1024**3
print(f"  {info.get('device_name')} — {budget:.1f} GiB GPU budget, "
      f"max buffer {info.get('max_buffer_length', 0) / 1024**3:.1f} GiB")
PYCHECK

# ── 2. Worker virtualenv ─────────────────────────────────────────────────────
WORKER_VENV="$INSTALL_ROOT/.venv"
PYTHON_BIN="${LOGOS_PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
    for candidate in python3.12 python3.13 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN="$(command -v "$candidate")"; break; fi
    done
fi
[ -n "$PYTHON_BIN" ] || die "No python3 found. Install one (e.g. brew install python@3.12)."

log "Worker venv:       $WORKER_VENV  (from $PYTHON_BIN)"
"$PYTHON_BIN" -m venv "$WORKER_VENV" 2>/dev/null || true
"$WORKER_VENV/bin/python" -m pip install --quiet --upgrade pip
"$WORKER_VENV/bin/python" -m pip install --quiet -r "$INSTALL_ROOT/requirements.txt"

# ── 3. Runtime directories ───────────────────────────────────────────────────
mkdir -p "$INSTALL_ROOT/data" "$INSTALL_ROOT/logs" "$INSTALL_ROOT/chat-templates"

# config.yml is operator state: seed it once, never overwrite on redeploy.
if [ ! -f "$INSTALL_ROOT/config.yml" ]; then
    cp "$INSTALL_ROOT/config.example.mlx.yml" "$INSTALL_ROOT/config.yml"
    warn "Seeded config.yml from the example — review it before starting."
    warn "  capabilities_models and model_profile_overrides need your models."
fi
if [ ! -f "$INSTALL_ROOT/.env" ]; then
    warn "No .env found at $INSTALL_ROOT/.env — the worker needs LOGOS_URL and LOGOS_API_KEY."
fi

log "Installation complete."
