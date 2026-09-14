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
# Pinned to the release this worker was verified against. v0.28.0 is the
# stable cut that contains the build the MACOS.md measurements were taken
# with (v0.3.0.dev20260826134128, plus its 14 follow-up bugfix commits) and
# vendors vLLM 0.28.0 — the combination the document describes. `main` and
# /releases/latest are deliberately not fetched anywhere: they carry no
# version guarantee, and the installer runs on a machine that will hold other
# people's prompts, so every byte that is executed or installed is pinned to
# the tag below and sha256-verified before use. Bump ref and checksums
# together when upgrading (and re-check the patch patterns below against the
# new installer — see the version-pinning section of MACOS.md).
VLLM_METAL_REF="v0.28.0"
VLLM_METAL_INSTALLER="https://raw.githubusercontent.com/vllm-project/vllm-metal/${VLLM_METAL_REF}/install.sh"
VLLM_METAL_INSTALLER_SHA256="0d0400a5527169cc2a2934189081c357464a64f3b463542e6f56921f036f984a"
# The pinned installer performs further fetches of its own before it installs
# anything — and it only checksums itself. At this tag it sources
# scripts/lib.sh from the mutable `main` branch (executed code!), selects the
# vllm-metal wheel from /releases/latest, and derives the vLLM core wheel URL
# from a release lookup. So each of those artifacts is fetched from the
# pinned tag and verified HERE, before the installer ever runs, and the
# installer is patched to consume the verified copies:
VLLM_METAL_LIB="https://raw.githubusercontent.com/vllm-project/vllm-metal/${VLLM_METAL_REF}/scripts/lib.sh"
VLLM_METAL_LIB_SHA256="874d05acf9601a3f68e7c1246179a7ca3bb3f2f9ed9856f5f71df4bdaf293da8"
VLLM_METAL_WHEEL_NAME="vllm_metal-0.28.0-cp312-cp312-macosx_15_0_arm64.whl"
VLLM_METAL_WHEEL_URL="https://github.com/vllm-project/vllm-metal/releases/download/${VLLM_METAL_REF}/${VLLM_METAL_WHEEL_NAME}"
VLLM_METAL_WHEEL_SHA256="61d7c410fe0f017b0268a306208582b23f1ac4e18e7ffd5472cf3631866d4b28"
# vLLM core wheel (cp312 — the installer's lib.sh creates the venv with
# Python 3.12). PyPI carries no macOS vLLM wheel, hence the release URL.
VLLM_CORE_WHEEL_NAME="vllm-0.28.0+cpu-cp312-cp312-macosx_11_0_arm64.whl"
VLLM_CORE_WHEEL_URL="https://github.com/vllm-project/vllm/releases/download/v0.28.0/vllm-0.28.0%2Bcpu-cp312-cp312-macosx_11_0_arm64.whl"
VLLM_CORE_WHEEL_SHA256="e8c5a3930367b740914a14420efcc3535da2c2dba5bb23d77221ff81094cc630"
# Documented floor (MACOS.md, Requirements): below it the current model set
# does not load.
VLLM_METAL_MIN_VERSION="0.28.0"

log()  { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; exit 1; }

# Download one pinned artifact and verify its sha256 before it may be
# sourced, installed or executed.
fetch_verified() {
    local url="$1" sha256="$2" dest="$3"
    if ! curl -fsSL "$url" -o "$dest"; then
        die "Could not download $(basename "$url") from $url."
    fi
    if ! echo "${sha256}  $dest" | shasum -a 256 -c - >/dev/null 2>&1; then
        rm -f "$dest"
        die "SHA256 checksum mismatch on $(basename "$url") — refusing to use an unverified artifact."
    fi
    log "  verified $(basename "$dest")"
}

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

# uv is the installer's package manager. It is required preinstalled rather
# than letting the installer bootstrap it — that bootstrap is a curl|sh of
# bytes we do not verify.
command -v uv >/dev/null 2>&1 || die "uv not found — install it first (brew install uv), then re-run."
command -v python3 >/dev/null 2>&1 || die "python3 not found — needed to verify and patch the installer and to create the worker venv (brew install python@3.12)."

log "Install root:      $INSTALL_ROOT"
log "vllm-metal venv:   $METAL_VENV"

# ── 1. vllm-metal virtualenv ─────────────────────────────────────────────────
# Deliberately delegated to upstream's installer rather than pinning versions
# here: vllm-metal ships a matched (vllm, mlx, torch) set, and picking those
# apart in our own requirements file is how you get an unbootable lane. What
# IS pinned is everything the installer executes or installs — the installer,
# its lib.sh, the vLLM core wheel and the vllm-metal wheel (tag + sha256, see
# above) — and the installer is patched to consume the verified copies.
if [ -x "$METAL_VENV/bin/vllm" ]; then
    log "vllm-metal already present — skipping install"
else
    log "Installing vllm-metal into $METAL_VENV (this downloads several GB)…"
    # The verified artifacts are staged in a directory of their own; the
    # installer gets a plain temp FILE, not a directory. That matters: if a
    # scripts/lib.sh sat next to the installer, upstream would take its
    # source-checkout branch (editable install, $PWD venv, native build)
    # instead of the wheel branch.
    stage="$(mktemp -d "${TMPDIR:-/tmp}/logos-vllm-metal-stage.XXXXXX")"
    installer_tmp="$(mktemp "${TMPDIR:-/tmp}/logos-vllm-metal-install.XXXXXX")"
    trap 'rm -rf "$stage" "$installer_tmp"' EXIT
    mkdir -p "$stage/scripts" "$stage/wheels"

    fetch_verified "$VLLM_METAL_LIB" "$VLLM_METAL_LIB_SHA256" "$stage/scripts/lib.sh"
    fetch_verified "$VLLM_METAL_WHEEL_URL" "$VLLM_METAL_WHEEL_SHA256" "$stage/wheels/$VLLM_METAL_WHEEL_NAME"
    fetch_verified "$VLLM_CORE_WHEEL_URL" "$VLLM_CORE_WHEEL_SHA256" "$stage/wheels/$VLLM_CORE_WHEEL_NAME"
    fetch_verified "$VLLM_METAL_INSTALLER" "$VLLM_METAL_INSTALLER_SHA256" "$installer_tmp"

    # Point the verified installer at the verified artifacts. At this tag it
    # still contains mutable fetches (lib.sh from `main`, the wheel from
    # /releases/latest) and a tag-derived vLLM wheel URL; each statement is
    # rewritten by exact string match to the staged copy. If upstream changes
    # any of those lines the occurrence count is not 1 and the install
    # aborts — a half-patched installer must never run. Re-verify the
    # patterns when bumping the pin.
    stage_real="$(cd "$stage" && pwd -P)"
    if ! python3 - "$installer_tmp" "$stage_real" "$VLLM_METAL_REF" "$VLLM_METAL_WHEEL_NAME" "$VLLM_CORE_WHEEL_NAME" <<'PATCH'
import sys

path, stage, release_tag, metal_wheel, vllm_wheel = sys.argv[1:6]
with open(path, encoding="utf-8") as f:
    src = f.read()

def pin(old, new, what):
    global src
    count = src.count(old)
    if count != 1:
        sys.exit(f"patch '{what}': expected exactly one occurrence, found {count}")
    src = src.replace(old, new)

pin(
    '    local lib_url="https://raw.githubusercontent.com/$repo_owner/$repo_name/main/scripts/lib.sh"',
    f'    local lib_url="file://{stage}/scripts/lib.sh"  # pinned + sha256-verified by logos install-macos.sh',
    "lib.sh source (was: mutable main branch)",
)
pin(
    '  local vllm_wheel_url="https://github.com/vllm-project/vllm/releases/download/${vllm_release_tag}/vllm-${vllm_version}%2Bcpu-cp312-cp312-macosx_11_0_arm64.whl"',
    f'  local vllm_wheel_url="{stage}/wheels/{vllm_wheel}"  # pinned + sha256-verified by logos install-macos.sh',
    "vLLM core wheel URL",
)
pin(
    """    release_data=$(fetch_release "$repo_owner" "$repo_name" "$channel")

    # extract_wheel_url prints the tag on the first line, the URL on the second.
    selected=$(printf '%s' "$release_data" | extract_wheel_url "$channel")
    release_tag=$(printf '%s' "$selected" | sed -n '1p')
    wheel_url=$(printf '%s' "$selected" | sed -n '2p')""",
    f"""    release_data=""
    selected=""
    release_tag="{release_tag}"
    wheel_url="file://{stage}/wheels/{metal_wheel}"  # pinned + sha256-verified by logos install-macos.sh""",
    "release selection (was: /releases/latest)",
)
pin(
    '    vllm_release_tag=$(fetch_release_vllm_tag "$repo_owner" "$repo_name" "$release_tag")',
    f'    vllm_release_tag="{release_tag}"  # pinned by logos install-macos.sh',
    "vLLM release tag fetch",
)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)
PATCH
    then
        die "The pinned vllm-metal installer does not match the expected layout — the pins in install-macos.sh are stale. Update ref, checksums and patch patterns together."
    fi

    bash "$installer_tmp"
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
