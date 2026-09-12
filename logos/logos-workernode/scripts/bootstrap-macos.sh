#!/usr/bin/env bash
# =============================================================================
# Logos Worker Node — set up a Mac as an MLX worker, from scratch
#
#   ./bootstrap-macos.sh [image-ref] [--no-deps] [--no-power-settings]
#
# Default image: ghcr.io/ls1intum/logos-workernode-mlx:latest
#
# This default must stay literally identical to the `images:` line for this
# image in .github/workflows/logos_build-and-push-docker.yml — that workflow
# is where the package is published, and nothing in CI catches a mismatch.
#
# This is the ONLY step needed on a freshly installed Mac. It installs its own
# prerequisites (Homebrew, git, uv, python@3.13), fetches and unpacks the
# distribution image, installs the runtime, registers the launchd agent and
# configures the machine to keep serving with the lid closed. Afterwards the
# node only needs to be registered as a provider in Logos and given its
# credentials in <install root>/.env.
#
# Re-running it is the upgrade path: everything is idempotent and operator
# state (config.yml, .env, data/, logs/, cache/) is preserved.
#
# The image is never started. Metal is unavailable inside containers, so the
# payload is extracted and the worker runs as a native launchd agent — which is
# also what lets it fork `vllm serve` subprocesses on orchestrator command.
#
# Because nothing is ever started, no container runtime is needed either: the
# image is pulled straight from the registry over HTTPS and its layers are
# untarred. That keeps Docker Desktop — a GUI application with a licence
# dialog on first launch — off a machine that is meant to run headless in a
# server room.
#
# Registry note: this image lives on ghcr.io (public), unlike every other Logos
# image, which is on Harbor. That is deliberate — a Mac worker should not need
# Harbor credentials just to bootstrap.
# =============================================================================
set -euo pipefail

IMAGE="${LOGOS_MLX_IMAGE:-ghcr.io/ls1intum/logos-workernode-mlx:latest}"
INSTALL_DEPS=1
POWER_SETTINGS=1
for arg in "$@"; do
    case "$arg" in
        --no-deps) INSTALL_DEPS=0 ;;
        --no-power-settings) POWER_SETTINGS=0 ;;
        -h|--help) sed -n '2,34p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) printf 'Unknown option: %s (try --help)\n' "$arg" >&2; exit 1 ;;
        *) IMAGE="$arg" ;;
    esac
done

INSTALL_ROOT="${LOGOS_MLX_HOME:-$HOME/logos-workernode-mlx}"
# The vllm-metal venv: one variable for the whole install, read by
# install-macos.sh, by the generated launchd plist (below) and by the worker's
# runtime resolvers (logos_worker_node.metal.default_metal_venv).
METAL_VENV="${LOGOS_METAL_VENV:-$HOME/.venv-vllm-metal}"
export LOGOS_METAL_VENV="$METAL_VENV"
LAUNCH_AGENT_LABEL="de.tum.logos.workernode"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
LAUNCH_AGENT_PLIST="$LAUNCH_AGENT_DIR/$LAUNCH_AGENT_LABEL.plist"
# Must satisfy install-macos.sh's own floor (WORKER_PYTHON_MIN_MINOR).
BREW_PYTHON="python@3.13"

log()  { printf '\033[1;36m[bootstrap]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bootstrap]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[bootstrap]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "macOS only (found $(uname -s))."
[ "$(uname -m)" = "arm64" ] || die "Apple Silicon required (found $(uname -m)). An x86_64/Rosetta Python cannot load MLX."

# ── 0. Prerequisites ─────────────────────────────────────────────────────────
# Everything here is skipped when already present, so this costs nothing on a
# re-run. --no-deps opts out entirely for machines whose toolchain is managed
# elsewhere (Ansible, MDM).
if [ "$INSTALL_DEPS" -eq 1 ]; then
    if ! command -v brew >/dev/null 2>&1; then
        # Apple Silicon installs to /opt/homebrew; check there too before
        # concluding it is missing, since a non-login shell may simply not
        # have run brew shellenv yet.
        if [ -x /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        else
            log "Installing Homebrew (asks for your password — it needs sudo)"
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
                || die "Homebrew installation failed."
            [ -x /opt/homebrew/bin/brew ] || die "Homebrew installed but /opt/homebrew/bin/brew is missing."
            eval "$(/opt/homebrew/bin/brew shellenv)"
            # Make it stick for future logins; the installer prints this as a
            # manual step, which a one-shot setup script should not leave to
            # the operator.
            if ! grep -qs 'brew shellenv' "$HOME/.zprofile" 2>/dev/null; then
                printf '\neval "$(/opt/homebrew/bin/brew shellenv)"\n' >> "$HOME/.zprofile"
                log "  added brew shellenv to ~/.zprofile"
            fi
        fi
    fi

    for formula in git uv "$BREW_PYTHON"; do
        if brew list --formula "$formula" >/dev/null 2>&1; then
            log "$formula already installed"
        else
            log "Installing $formula"
            brew install "$formula" || die "brew install $formula failed."
        fi
    done
fi

command -v uv >/dev/null 2>&1 \
    || die "uv not found. Re-run without --no-deps, or: brew install uv"

# ── 1. Fetch and unpack the image (no container runtime involved) ────────────
# Anonymous pull against the OCI distribution API: ghcr issues a pull token for
# public packages without credentials. Only `payload/` is extracted from each
# layer — the rest of the image filesystem is irrelevant here, and narrowing
# the extraction keeps a hostile layer from writing outside it.
STAGING="$(mktemp -d)"
UNPACK="$(mktemp -d)"
cleanup() { rm -rf "$STAGING" "$UNPACK"; }
trap cleanup EXIT

registry_ref() {
    # ghcr.io/ls1intum/logos-workernode-mlx:latest → registry, repo, reference
    local ref="$1" rest
    REGISTRY="${ref%%/*}"
    rest="${ref#*/}"
    case "$rest" in
        *:*) REPO="${rest%:*}"; REFERENCE="${rest##*:}" ;;
        *)   REPO="$rest";      REFERENCE="latest" ;;
    esac
}
registry_ref "$IMAGE"

log "Fetching $IMAGE"
TOKEN="$(curl -fsSL "https://${REGISTRY}/token?scope=repository:${REPO}:pull&service=${REGISTRY}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' 2>/dev/null)" \
    || die "Could not obtain a pull token for ${REPO} from ${REGISTRY}."

ACCEPT="application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.docker.distribution.manifest.v2+json"

curl -fsSL -H "Authorization: Bearer $TOKEN" -H "Accept: $ACCEPT" \
    "https://${REGISTRY}/v2/${REPO}/manifests/${REFERENCE}" -o "$UNPACK/manifest.json" \
    || die "Could not fetch the manifest for ${IMAGE}."

# A multi-arch index needs one more hop to the arm64 manifest; a single-arch
# manifest is already the thing we want.
SUB_DIGEST="$(python3 - "$UNPACK/manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for entry in m.get("manifests", []):
    p = entry.get("platform", {})
    if p.get("architecture") == "arm64" and p.get("os") == "linux":
        print(entry["digest"])
        break
PY
)"
if [ -n "$SUB_DIGEST" ]; then
    curl -fsSL -H "Authorization: Bearer $TOKEN" -H "Accept: $ACCEPT" \
        "https://${REGISTRY}/v2/${REPO}/manifests/${SUB_DIGEST}" -o "$UNPACK/manifest.json" \
        || die "Could not fetch the arm64 manifest for ${IMAGE}."
fi

LAYERS="$(python3 - "$UNPACK/manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
layers = m.get("layers")
if not layers:
    sys.exit("manifest carries no layers")
print("\n".join(l["digest"] for l in layers))
PY
)" || die "Unexpected manifest format for ${IMAGE}."

log "Unpacking $(printf '%s\n' "$LAYERS" | wc -l | tr -d ' ') layers"
while IFS= read -r layer; do
    [ -n "$layer" ] || continue
    # Download first, extract second. Piping curl into tar would conflate a
    # failed transfer with "this layer has no payload/", and only the latter is
    # acceptable: the payload is spread over several layers, so a half-fetched
    # one yields an incomplete tree that the --delete sync below would then
    # publish over a working installation.
    blob="$UNPACK/layer.tar.gz"
    curl -fsSL -H "Authorization: Bearer $TOKEN" \
        "https://${REGISTRY}/v2/${REPO}/blobs/${layer}" -o "$blob" \
        || die "Failed to download layer ${layer%%:*}:${layer#*:} — aborting rather than deploying a partial payload."

    # Verify the content digest the manifest states. A container runtime does
    # this for every layer; replacing it with curl means doing it here, or a
    # registry or transport fault that hands back a different — still perfectly
    # readable — archive would be synced straight into the live installation.
    # This is the same standard install-macos.sh applies to every byte it
    # executes.
    case "${layer%%:*}" in
        sha256) actual="$(shasum -a 256 "$blob" | cut -d' ' -f1)" ;;
        sha512) actual="$(shasum -a 512 "$blob" | cut -d' ' -f1)" ;;
        *) die "Layer uses unsupported digest algorithm '${layer%%:*}' — refusing to trust it." ;;
    esac
    if [ "$actual" != "${layer#*:}" ]; then
        die "Digest mismatch on layer ${layer#*:}
  expected ${layer#*:}
  got      $actual
Refusing to unpack an artifact that is not what the manifest describes."
    fi

    # Layers are applied in order so later ones win, exactly as a container
    # runtime would compose them. Listing first distinguishes the two cases a
    # bare extract cannot: a layer that genuinely carries no payload/ (normal,
    # base image layers) versus a corrupt archive (fatal).
    if ! tar -tzf "$blob" >/dev/null 2>&1; then
        die "Layer ${layer#*:} is not a readable gzip archive — aborting."
    fi
    if tar -tzf "$blob" 2>/dev/null | grep -q '^payload/'; then
        tar -xzf "$blob" -C "$UNPACK" payload \
            || die "Failed to extract payload/ from layer ${layer#*:}."

        # Apply OCI whiteouts, which a container runtime does when it composes
        # layers and a plain sequential untar does not. Without this a file
        # deleted in a later layer survives into staging and is then synced
        # into the installation — the payload is assembled across layers, so a
        # file removed from the image would come back on every deploy.
        #
        # Per the image-layer spec: `.wh.<name>` deletes <name> in the same
        # directory, and `.wh..wh..opq` clears the directory's inherited
        # contents. Applied after each layer rather than once at the end,
        # because a later layer may legitimately re-add what an earlier one
        # deleted.
        while IFS= read -r marker; do
            [ -n "$marker" ] || continue
            marker_dir="$(dirname "$marker")"
            marker_name="$(basename "$marker")"
            if [ "$marker_name" = ".wh..wh..opq" ]; then
                find "$marker_dir" -mindepth 1 -maxdepth 1 ! -name '.wh..wh..opq' -exec rm -rf {} + 2>/dev/null || true
            else
                rm -rf "${marker_dir}/${marker_name#.wh.}"
            fi
            rm -f "$marker"
        done <<WHITEOUTS
$(find "$UNPACK/payload" -name '.wh.*' 2>/dev/null)
WHITEOUTS
    fi
    rm -f "$blob"
done <<EOF
$LAYERS
EOF

[ -d "$UNPACK/payload" ] || die "The image contains no /payload directory — is $IMAGE the MLX worker image?"
[ -f "$UNPACK/payload/requirements.txt" ] || die "Extracted payload looks incomplete (requirements.txt missing)."
mv "$UNPACK/payload/." "$STAGING/" 2>/dev/null || cp -R "$UNPACK/payload/." "$STAGING/"
log "Payload staged in $STAGING"

# Stop the agent before swapping code underneath it, so a half-copied
# logos_worker_node/ can never be imported by a live process.
if launchctl list "$LAUNCH_AGENT_LABEL" >/dev/null 2>&1; then
    log "Stopping running worker"
    launchctl bootout "gui/$(id -u)/$LAUNCH_AGENT_LABEL" 2>/dev/null || true
fi

mkdir -p "$INSTALL_ROOT"
# Sync code only. data/, logs/, config.yml, .env, .venv and cache/ are operator
# or runtime state and must survive a redeploy — hence the explicit excludes
# rather than a wholesale copy. cache/ matters most: --delete removes anything
# absent from the image, and the seeded config points cache_path at
# <install root>/cache, so leaving it out of this list silently discards every
# downloaded model (tens of GB) on each upgrade.
log "Syncing code into $INSTALL_ROOT"
rsync -a --delete \
    --exclude 'data/' \
    --exclude 'logs/' \
    --exclude 'config.yml' \
    --exclude '.env' \
    --exclude '.venv/' \
    --exclude 'cache/' \
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

# ── 5. Keep the machine awake ────────────────────────────────────────────────
# A MacBook idles into sleep within minutes and takes the node offline with it;
# closing the lid does the same immediately. Both are fatal for a worker that
# is supposed to answer whenever the orchestrator routes to it. disablesleep
# also covers the closed-lid case, which the per-source timers do not.
if [ "$POWER_SETTINGS" -eq 1 ]; then
    if [ "$(pmset -g 2>/dev/null | awk '/SleepDisabled/ {print $2}')" = "1" ]; then
        log "Sleep already disabled"
    else
        log "Configuring the machine to keep running (asks for your password)"
        if sudo pmset -a disablesleep 1 2>/dev/null \
           && sudo pmset -c sleep 0 displaysleep 0 disksleep 0 standby 0 autopoweroff 0 powernap 0 2>/dev/null; then
            log "  sleep disabled, AC timers zeroed"
        else
            warn "Could not change the power settings. Run by hand, or the node drops off when idle:"
            warn "    sudo pmset -a disablesleep 1"
            warn "    sudo pmset -c sleep 0 displaysleep 0 disksleep 0 standby 0 autopoweroff 0 powernap 0"
        fi
    fi
fi

echo
log "Done — the worker is running and waiting for credentials."
echo
echo "  Two things are left, both server-side:"
echo
echo "  1. Register this Mac as a provider in the Logos UI and copy its worker key."
echo "     Pick the privacy level that matches where the machine physically is:"
echo "     LOCAL for your own datacentre, THIRD_PARTY_HARDWARE for a machine"
echo "     whose operator is not you — a Metal lane is a native process, so its"
echo "     operator can read the prompts it serves."
echo
echo "  2. Write the credentials and restart the agent:"
echo
echo "       cat > $INSTALL_ROOT/.env <<'ENV'"
echo "       LOGOS_URL=https://logos.example.tum.de"
echo "       LOGOS_API_KEY=<worker key from step 1>"
echo "       ENV"
echo "       chmod 600 $INSTALL_ROOT/.env"
echo "       launchctl kickstart -k gui/\$(id -u)/$LAUNCH_AGENT_LABEL"
echo
echo "  Then review $INSTALL_ROOT/config.yml — capabilities_models and"
echo "  model_profile_overrides decide which models this node advertises."
echo
log "  logs:     tail -f $INSTALL_ROOT/logs/worker.log"
log "  status:   launchctl print gui/$(id -u)/$LAUNCH_AGENT_LABEL | head -20"
log "  stop:     launchctl bootout gui/$(id -u)/$LAUNCH_AGENT_LABEL"
