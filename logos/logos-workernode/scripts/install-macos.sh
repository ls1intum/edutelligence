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
# One venv variable for the whole install: bootstrap-macos.sh, the generated
# launchd plist and the worker's runtime resolvers (default_metal_venv) read
# the same LOGOS_METAL_VENV, so a custom location cannot be installed into and
# then missed at lane spawn.
METAL_VENV="${LOGOS_METAL_VENV:-$HOME/.venv-vllm-metal}"
# Pinned to the release this worker was verified against (it vendors vLLM
# 0.28.0 — the combination MACOS.md documents). `main` is deliberately not
# fetched: it carries no version guarantee, and the installer runs on a
# machine that will hold other people's prompts, so the exact bytes that run
# must be reproducible. Bump the ref and the checksum together when upgrading.
VLLM_METAL_REF="v0.3.0.dev20260826134128"
VLLM_METAL_INSTALLER="https://raw.githubusercontent.com/vllm-project/vllm-metal/${VLLM_METAL_REF}/install.sh"
VLLM_METAL_INSTALLER_SHA256="e1aa5b82aaa2e3ed2432b7cd4826561779dad0f6d16cee444372b6677887bbfa"
# Documented floor (MACOS.md, Requirements): below it the current model set
# does not load.
VLLM_METAL_MIN_VERSION="0.3.0.dev20260826"

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
# apart in our own requirements file is how you get an unbootable lane. What
# IS pinned is the installer itself — a release tag plus checksum, see above;
# the installer is what selects the (vllm, mlx, torch) set.
if [ -x "$METAL_VENV/bin/vllm" ]; then
    log "vllm-metal already present — skipping install"
else
    log "Installing vllm-metal into $METAL_VENV (this downloads several GB)…"
    installer_tmp="$(mktemp "${TMPDIR:-/tmp}/vllm-metal-install.XXXXXX")"
    if ! curl -fsSL "$VLLM_METAL_INSTALLER" -o "$installer_tmp"; then
        rm -f "$installer_tmp"
        die "Could not download the vllm-metal installer from $VLLM_METAL_INSTALLER."
    fi
    if ! echo "${VLLM_METAL_INSTALLER_SHA256}  $installer_tmp" | shasum -a 256 -c - >/dev/null 2>&1; then
        rm -f "$installer_tmp"
        die "SHA256 checksum mismatch on the vllm-metal installer — refusing to run an unverified installer."
    fi
    bash "$installer_tmp"
    rm -f "$installer_tmp"
    if [ ! -x "$METAL_VENV/bin/vllm" ] && [ -x "$HOME/.venv-vllm-metal/bin/vllm" ]; then
        die "vllm-metal was installed into $HOME/.venv-vllm-metal, but LOGOS_METAL_VENV points at $METAL_VENV.
Upstream's installer always creates ~/.venv-vllm-metal — populate a custom location yourself (e.g. upstream's editable install) or unset LOGOS_METAL_VENV."
    fi
    [ -x "$METAL_VENV/bin/vllm" ] || die "vllm-metal install finished but $METAL_VENV/bin/vllm is missing."
fi

# Enforce the documented version floor on every run — fresh install and
# pre-existing venv alike, so a venv left behind by an older installer
# generation fails here instead of at first model load.
log "Verifying the vllm-metal version floor (>= $VLLM_METAL_MIN_VERSION)…"
"$METAL_VENV/bin/python" - "$VLLM_METAL_MIN_VERSION" <<'PYFLOOR' || die "vllm-metal is below the version floor this worker requires — remove the venv and re-run the installer."
import importlib.metadata as m
import sys

from packaging.version import InvalidVersion, Version

installed = m.version("vllm-metal")
floor = Version(sys.argv[1])
try:
    ok = Version(installed) >= floor
except InvalidVersion:
    ok = False
if not ok:
    print(f"  vllm-metal {installed!r} is below the required {floor}", file=sys.stderr)
    sys.exit(1)
print(f"  vllm-metal {installed} OK (floor {floor})")
PYFLOOR

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
