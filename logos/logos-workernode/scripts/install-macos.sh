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
# Pinned to the release this worker was verified against. v0.29.0 vendors
# vLLM 0.29.0 and is the first cut that loads the official Qwen3-Embedding
# checkpoints: those ship their backbone weights flat (`embed_tokens.weight`,
# `layers.0.…`) while mlx-lm's Qwen3 wraps them under `model.`, so on v0.28.0
# every tensor was rejected with "Received 398 parameters not in model"
# (vllm-metal#730, fixed by a key remap in #736). The MLX re-quantizations of
# the same model failed differently and just as fatally — the generation
# loader demanded an `lm_head.weight` an embedder does not carry. Verified on
# an M2 Pro: `Qwen/Qwen3-Embedding-8B` with `--runner pooling` now serves
# 4096-dimensional vectors. `main` and /releases/latest are deliberately not
# fetched anywhere: they carry no version guarantee, and the installer runs on
# a machine that will hold other people's prompts, so every byte that is
# executed or installed is pinned to the tag below and sha256-verified before
# use. Bump ref and checksums together when upgrading (and re-check the patch
# patterns below against the new installer — see the version-pinning section
# of MACOS.md).
VLLM_METAL_REF="v0.29.0"
VLLM_METAL_INSTALLER="https://raw.githubusercontent.com/vllm-project/vllm-metal/${VLLM_METAL_REF}/install.sh"
# Unchanged from v0.28.0 on purpose, not an oversight: install.sh and
# scripts/lib.sh are byte-identical at both tags (re-verified against
# v0.29.0), so only the wheels below move. Always re-compute these when
# bumping — an identical checksum is a fact to confirm, never to assume.
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
VLLM_METAL_WHEEL_NAME="vllm_metal-0.29.0-cp312-cp312-macosx_15_0_arm64.whl"
VLLM_METAL_WHEEL_URL="https://github.com/vllm-project/vllm-metal/releases/download/${VLLM_METAL_REF}/${VLLM_METAL_WHEEL_NAME}"
VLLM_METAL_WHEEL_SHA256="0d03dcc2be9a4286a19c5e53e1355d2e47acdbf2be6f9de9cbb48cc4b880f393"
# vLLM core wheel (cp312 — the installer's lib.sh creates the venv with
# Python 3.12). PyPI carries no macOS vLLM wheel, hence the release URL.
VLLM_CORE_WHEEL_NAME="vllm-0.29.0+cpu-cp312-cp312-macosx_11_0_arm64.whl"
VLLM_CORE_WHEEL_URL="https://github.com/vllm-project/vllm/releases/download/v0.29.0/vllm-0.29.0%2Bcpu-cp312-cp312-macosx_11_0_arm64.whl"
VLLM_CORE_WHEEL_SHA256="7133cb494664c502b07b114fe915847f0e71296d502f67f6fa76172ba46978df"
# Documented floor (MACOS.md, Requirements): below it the current model set
# does not load.
VLLM_METAL_MIN_VERSION="0.29.0"

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
# Any python3 will do for the patch step below (it only rewrites text); the
# worker venv has a real version floor and picks its own interpreter later.
command -v python3 >/dev/null 2>&1 || die "python3 not found — needed to verify and patch the installer (brew install python@3.13)."

log "Install root:      $INSTALL_ROOT"
log "vllm-metal venv:   $METAL_VENV"

# ── 1. vllm-metal virtualenv ─────────────────────────────────────────────────
# Deliberately delegated to upstream's installer rather than pinning versions
# here: vllm-metal ships a matched (vllm, mlx, torch) set, and picking those
# apart in our own requirements file is how you get an unbootable lane. What
# IS pinned is everything the installer executes or installs — the installer,
# its lib.sh, the vLLM core wheel and the vllm-metal wheel (tag + sha256, see
# above) — and the installer is patched to consume the verified copies.
# Skipping on "a vllm exists" alone is what made a version bump undeployable:
# an existing 0.28 venv took the skip path, the floor check below then failed,
# and because bootstrap-macos.sh boots the agent out before running this, the
# documented upgrade command left the node offline until someone deleted the
# venv by hand. Compare against the pin instead of merely testing for presence,
# and rebuild when they differ — upstream's installer creates the venv with
# --clear, but an explicit removal keeps a half-written venv from being
# reused.
installed_metal_version() {
    [ -x "$METAL_VENV/bin/python" ] || return 1
    "$METAL_VENV/bin/python" -c 'import importlib.metadata as m; print(m.version("vllm-metal"))' 2>/dev/null
}

# Put the previous venv back if anything between the move and the successful
# verification fails — a half-finished upgrade must not leave the node with no
# runtime at all.
rollback_stale_metal_venv() {
    local rc="$1"
    [ "$rc" -ne 0 ] || return 0
    [ -n "${stale_metal_venv:-}" ] && [ -d "$stale_metal_venv" ] || return 0
    warn "Install failed — restoring the previous vllm-metal venv"
    rm -rf "$METAL_VENV"
    mv "$stale_metal_venv" "$METAL_VENV" \
        && warn "  restored $METAL_VENV (still the old version; re-run to retry the upgrade)" \
        || warn "  could not restore it; the previous venv is in $stale_metal_venv"
}
trap 'rollback_stale_metal_venv $?' EXIT
# Is the installed version at or above the documented floor? Same comparison
# the floor check further down performs, asked early so a custom venv is judged
# by the requirement rather than by the pin.
metal_meets_floor() {
    "$METAL_VENV/bin/python" - "${1:-}" "$VLLM_METAL_MIN_VERSION" <<'PYFLOORCHK' 2>/dev/null
import sys

from packaging.version import InvalidVersion, Version

try:
    sys.exit(0 if Version(sys.argv[1]) >= Version(sys.argv[2]) else 1)
except (InvalidVersion, IndexError):
    sys.exit(1)
PYFLOORCHK
}

metal_needs_install=1
stale_metal_venv=""
if [ -x "$METAL_VENV/bin/vllm" ]; then
    current_metal="$(installed_metal_version || true)"
    # The two locations are held to different standards on purpose. The default
    # venv is managed by this script, so it tracks the pin exactly and is
    # rebuilt on any difference — that is what makes a deployment
    # reproducible. A custom venv is the operator's, and the documented
    # contract for it is VLLM_METAL_MIN_VERSION, a floor: rejecting a newer
    # build (0.30.0 against a 0.29.0 floor) would strand a perfectly
    # compatible environment, and since the branch below cannot rebuild custom
    # paths it would abort — with the worker already stopped when run through
    # the bootstrap.
    if [ "$METAL_VENV" != "$HOME/.venv-vllm-metal" ]; then
        if metal_meets_floor "$current_metal"; then
            log "vllm-metal ${current_metal:-unknown} in $METAL_VENV meets the floor ($VLLM_METAL_MIN_VERSION) — skipping install"
            metal_needs_install=0
        else
            die "vllm-metal ${current_metal:-unknown} in $METAL_VENV is below the required $VLLM_METAL_MIN_VERSION.
LOGOS_METAL_VENV points at a custom location, which upstream's installer cannot
populate, so this script will not delete it. Upgrade or remove that venv
yourself, or unset LOGOS_METAL_VENV to use the default."
        fi
    elif [ "$current_metal" = "$VLLM_METAL_MIN_VERSION" ]; then
        log "vllm-metal $current_metal already present — skipping install"
        metal_needs_install=0
    else
        log "vllm-metal ${current_metal:-unknown} is installed but this worker pins $VLLM_METAL_MIN_VERSION — rebuilding the venv"
        # Move aside instead of deleting: if the download or install below
        # fails, the node still has a working (if outdated) runtime to fall
        # back on rather than no runtime at all. Removed once the new venv is
        # verified.
        stale_metal_venv="$METAL_VENV.stale-$$"
        mv "$METAL_VENV" "$stale_metal_venv"
    fi
fi
if [ "$metal_needs_install" -eq 1 ]; then
    log "Installing vllm-metal into $METAL_VENV (this downloads several GB)…"
    # The verified artifacts are staged in a directory of their own; the
    # installer gets a plain temp FILE, not a directory. That matters: if a
    # scripts/lib.sh sat next to the installer, upstream would take its
    # source-checkout branch (editable install, $PWD venv, native build)
    # instead of the wheel branch.
    stage="$(mktemp -d "${TMPDIR:-/tmp}/logos-vllm-metal-stage.XXXXXX")"
    installer_tmp="$(mktemp "${TMPDIR:-/tmp}/logos-vllm-metal-install.XXXXXX")"
    # Keeps the rollback armed: a bare `trap ... EXIT` here would replace the
    # handler installed above and silently drop the venv restore.
    trap 'rc=$?; rm -rf "$stage" "$installer_tmp"; rollback_stale_metal_venv $rc' EXIT
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

# The replacement is installed, at the pinned version, with a loadable plugin —
# only now is the previous venv safe to discard. Until this point the rollback
# handler would have put it back.
if [ -n "${stale_metal_venv:-}" ] && [ -d "$stale_metal_venv" ]; then
    log "Removing the superseded vllm-metal venv"
    rm -rf "$stale_metal_venv"
    stale_metal_venv=""
fi

# ── 2. Worker virtualenv ─────────────────────────────────────────────────────
# The floor is 3.12: the worker's own dependencies are fine further back, but
# pydantic v2 evaluates `bool | None` annotations at import, which needs 3.10+,
# and 3.12 is what the rest of this installer is built around.
WORKER_PYTHON_MIN_MINOR=12

# Print the minor version of a CPython 3.x interpreter, or nothing if it is not
# a usable python3 at all.
python_minor() {
    "$1" -c 'import sys; print(sys.version_info[1] if sys.version_info[0] == 3 else "")' 2>/dev/null
}

WORKER_VENV="$INSTALL_ROOT/.venv"
PYTHON_BIN="${LOGOS_PYTHON:-}"
if [ -n "$PYTHON_BIN" ]; then
    # An explicit LOGOS_PYTHON is honoured but still checked — a stale value is
    # exactly as fatal as a bad auto-pick, and much more surprising.
    minor="$(python_minor "$PYTHON_BIN")"
    [ -n "$minor" ] || die "LOGOS_PYTHON=$PYTHON_BIN is not a usable python3."
    [ "$minor" -ge "$WORKER_PYTHON_MIN_MINOR" ] || die \
        "LOGOS_PYTHON=$PYTHON_BIN is Python 3.$minor; this worker needs 3.$WORKER_PYTHON_MIN_MINOR or newer."
else
    # Preferred version first, NOT newest first. python3.13 is what
    # bootstrap-macos.sh installs and what this worker is tested against;
    # picking the newest interpreter present would rebuild the venv onto an
    # untested Python the moment someone installs a newer one for unrelated
    # reasons — and the rebuild branch below would do it on every run.
    # Newer versions are still accepted when nothing preferred is installed.
    #
    # macOS always has /usr/bin/python3 (Command Line Tools, 3.9), and Homebrew
    # only symlinks a bare `python3` for its current default formula — so a
    # machine with just `brew install python@3.14` has no `python3` of its own
    # and the bare name resolves to Apple's 3.9. Picking it silently is what
    # produced a venv that failed much later, at import time, with an
    # unrelated-looking pydantic error. Hence: every candidate is
    # version-checked, and there is no unchecked fallback.
    for candidate in python3.13 python3.12 python3.14 python3.15 python3; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        resolved="$(command -v "$candidate")"
        minor="$(python_minor "$resolved")"
        [ -n "$minor" ] && [ "$minor" -ge "$WORKER_PYTHON_MIN_MINOR" ] || continue
        PYTHON_BIN="$resolved"
        break
    done
fi
[ -n "$PYTHON_BIN" ] || die "No Python 3.$WORKER_PYTHON_MIN_MINOR+ found.
macOS ships only Python 3.9 (/usr/bin/python3), which cannot run this worker.
Install a supported one and re-run:

  brew install python@3.13

Homebrew creates a versioned 'python3.13' binary; this installer finds it on
PATH. Use LOGOS_PYTHON=/path/to/python3.13 to point at a specific interpreter."

log "Worker venv:       $WORKER_VENV  (from $PYTHON_BIN, Python 3.$(python_minor "$PYTHON_BIN"))"

# `python -m venv` on an existing directory does NOT replace bin/python when it
# already exists — it only adds the version-suffixed name. A venv first created
# with 3.9 therefore keeps launching 3.9 after a re-run with a newer
# interpreter, while pyvenv.cfg claims the new version. Recreate instead of
# patching over it whenever the interpreter on disk is not the one we want.
if [ -x "$WORKER_VENV/bin/python" ]; then
    have="$(python_minor "$WORKER_VENV/bin/python")"
    want="$(python_minor "$PYTHON_BIN")"
    if [ "$have" != "$want" ]; then
        log "  existing venv runs Python 3.${have:-?}, rebuilding it for 3.$want"
        rm -rf "$WORKER_VENV"
    fi
fi
"$PYTHON_BIN" -m venv "$WORKER_VENV"
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
