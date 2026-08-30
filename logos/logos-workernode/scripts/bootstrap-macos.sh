#!/usr/bin/env bash
# =============================================================================
# Logos Worker Node — pull the MLX distribution image and install it natively
#
#   ./bootstrap-macos.sh [image-ref]
#
# Default image: ghcr.io/ls1intum/logos-workernode-mlx:latest
#
# This default must stay literally identical to the `images:` line for this
# image in .github/workflows/logos_build-and-push-docker.yml — that workflow
# is where the package is published, and nothing in CI catches a mismatch.
#
# The image is never started. Metal is unavailable inside containers, so the
# payload is extracted and the worker runs as a native launchd agent — which is
# also what lets it fork `vllm serve` subprocesses on orchestrator command.
#
# Registry note: this image lives on ghcr.io (public), unlike every other Logos
# image, which is on Harbor. That is deliberate — a Mac worker should not need
# Harbor credentials just to bootstrap. `docker login ghcr.io` is only needed
# while the package is still private.
# =============================================================================
set -euo pipefail

IMAGE="${1:-${LOGOS_MLX_IMAGE:-ghcr.io/ls1intum/logos-workernode-mlx:latest}}"
INSTALL_ROOT="${LOGOS_MLX_HOME:-$HOME/logos-workernode-mlx}"
# The vllm-metal venv: one variable for the whole install, read by
# install-macos.sh, by the generated launchd plist (below) and by the worker's
# runtime resolvers (logos_worker_node.metal.default_metal_venv).
METAL_VENV="${LOGOS_METAL_VENV:-$HOME/.venv-vllm-metal}"
export LOGOS_METAL_VENV="$METAL_VENV"
LAUNCH_AGENT_LABEL="de.tum.logos.workernode"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
LAUNCH_AGENT_PLIST="$LAUNCH_AGENT_DIR/$LAUNCH_AGENT_LABEL.plist"

log()  { printf '\033[1;36m[bootstrap]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bootstrap]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[bootstrap]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "macOS only (found $(uname -s))."
command -v docker >/dev/null 2>&1 || die "docker not found — needed to fetch and unpack the image."

# ── 1. Fetch the artifact ────────────────────────────────────────────────────
log "Pulling $IMAGE"
docker pull "$IMAGE" || die "Pull failed. If the GHCR package is still private, run:
  echo \$GITHUB_TOKEN | docker login ghcr.io -u <your-username> --password-stdin"

# ── 2. Extract the payload ───────────────────────────────────────────────────
# `docker create` makes a container without starting it; nothing in the image
# ever executes. Its CMD deliberately exits non-zero to make that explicit.
CONTAINER_ID="$(docker create "$IMAGE")"
cleanup() { docker rm -f "$CONTAINER_ID" >/dev/null 2>&1 || true; }
trap cleanup EXIT

STAGING="$(mktemp -d)"
log "Extracting payload to $STAGING"
docker cp "$CONTAINER_ID:/payload/." "$STAGING/"

# Stop the agent before swapping code underneath it, so a half-copied
# logos_worker_node/ can never be imported by a live process.
if launchctl list "$LAUNCH_AGENT_LABEL" >/dev/null 2>&1; then
    log "Stopping running worker"
    launchctl bootout "gui/$(id -u)/$LAUNCH_AGENT_LABEL" 2>/dev/null || true
fi

mkdir -p "$INSTALL_ROOT"
# Sync code only. data/, logs/, config.yml, .env and .venv are operator or
# runtime state and must survive a redeploy — hence the explicit excludes
# rather than a wholesale copy.
log "Syncing code into $INSTALL_ROOT"
rsync -a --delete \
    --exclude 'data/' \
    --exclude 'logs/' \
    --exclude 'config.yml' \
    --exclude '.env' \
    --exclude '.venv/' \
    --exclude 'chat-templates/' \
    "$STAGING/" "$INSTALL_ROOT/"

# chat-templates/ is excluded from the sync like config.yml — it is operator
# state (custom and edited templates). But unlike config.yml, the image
# packages a set of templates and the launchd agent points
# LOGOS_CHAT_TEMPLATE_DIR at this directory, so a plain exclude would leave it
# empty after the first deploy and every template referenced in config.yml
# would fail the lane spawn. Seed and merge with the config.yml rule: files
# the host does not have yet are copied in from the package, files that are
# already present (operator-managed) are never touched.
if [ -d "$STAGING/chat-templates" ]; then
    log "Merging packaged chat templates into $INSTALL_ROOT/chat-templates"
    mkdir -p "$INSTALL_ROOT/chat-templates"
    while IFS= read -r -d '' template; do
        target="$INSTALL_ROOT/chat-templates/${template#"$STAGING/chat-templates/"}"
        if [ ! -e "$target" ]; then
            mkdir -p "$(dirname "$target")"
            cp -p "$template" "$target"
        fi
    done < <(find "$STAGING/chat-templates" -type f -print0)
fi
rm -rf "$STAGING"

# ── 3. Install runtime dependencies ──────────────────────────────────────────
log "Running installer"
bash "$INSTALL_ROOT/scripts/install-macos.sh" "$INSTALL_ROOT"

# ── 4. launchd agent ─────────────────────────────────────────────────────────
# A LaunchAgent, not a LaunchDaemon: daemons run outside a login session and do
# not reliably get GPU access on macOS, which would silently drop every lane to
# the CPU. The tradeoff is that the account must be logged in — see MACOS.md
# for the auto-login setup on an unattended machine.
log "Installing launchd agent"
mkdir -p "$LAUNCH_AGENT_DIR"
# The template is named launchd-agent.plist.template rather than after the
# label: the repo's .gitignore has a `*.log*` rule, which "de.tum.logos.…"
# matches, so a label-named file would be silently untracked.
sed -e "s|@INSTALL_ROOT@|$INSTALL_ROOT|g" \
    -e "s|@LABEL@|$LAUNCH_AGENT_LABEL|g" \
    -e "s|@METAL_VENV@|$METAL_VENV|g" \
    "$INSTALL_ROOT/scripts/launchd-agent.plist.template" > "$LAUNCH_AGENT_PLIST"

launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENT_PLIST" 2>/dev/null \
    || launchctl kickstart -k "gui/$(id -u)/$LAUNCH_AGENT_LABEL"

log "Done. The worker is starting."
log "  logs:     tail -f $INSTALL_ROOT/logs/worker.log"
log "  status:   launchctl print gui/$(id -u)/$LAUNCH_AGENT_LABEL | head -20"
log "  stop:     launchctl bootout gui/$(id -u)/$LAUNCH_AGENT_LABEL"
