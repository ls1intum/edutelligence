#!/usr/bin/env bash
# =============================================================================
# Logos Worker Node — remove a native macOS (MLX) installation
#
#   ./uninstall-macos.sh [--keep-cache] [--keep-power-settings] [--yes]
#
# Removes what bootstrap-macos.sh and install-macos.sh created:
#
#   ~/Library/LaunchAgents/de.tum.logos.workernode.plist   the launchd agent
#   ~/logos-workernode-mlx                                 code, config, logs,
#                                                          .env, data, cache
#   ~/.venv-vllm-metal                                     the vllm-metal venv
#   ghcr.io/ls1intum/logos-workernode-mlx                  the pulled image
#
# It deliberately does NOT touch:
#
#   ~/.cache/huggingface   the user's own HF cache. The worker keeps its
#                          models under <install root>/cache/.hf_cache, so a
#                          shared cache outside the install root belongs to
#                          someone else's work.
#   Homebrew, uv, uv-managed Pythons   installed as prerequisites and
#                          routinely shared with other tools.
#
# Paths honour the same LOGOS_MLX_HOME / LOGOS_METAL_VENV overrides as the
# installer, so a non-default install is removed from where it actually is.
# =============================================================================
set -euo pipefail

INSTALL_ROOT="${LOGOS_MLX_HOME:-$HOME/logos-workernode-mlx}"
METAL_VENV="${LOGOS_METAL_VENV:-$HOME/.venv-vllm-metal}"
IMAGE="${LOGOS_MLX_IMAGE:-ghcr.io/ls1intum/logos-workernode-mlx}"
LAUNCH_AGENT_LABEL="de.tum.logos.workernode"
LAUNCH_AGENT_PLIST="$HOME/Library/LaunchAgents/$LAUNCH_AGENT_LABEL.plist"

KEEP_CACHE=0
KEEP_POWER=0
ASSUME_YES=0

log()  { printf '\033[1;36m[uninstall]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[uninstall]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[uninstall]\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        # The model cache is the expensive part — 15 GB per 8B model, and a
        # re-install would download it again. Worth keeping when the node is
        # only being rebuilt.
        --keep-cache) KEEP_CACHE=1 ;;
        --keep-power-settings) KEEP_POWER=1 ;;
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Unknown option: $1 (try --help)" ;;
    esac
    shift
done

[ "$(uname -s)" = "Darwin" ] || die "macOS only (found $(uname -s))."

# ── Path safety ──────────────────────────────────────────────────────────────
# Both paths below are environment-controlled and both are handed to `rm -rf`.
# A stale or mistyped LOGOS_MLX_HOME (say, "$HOME", or a value with an unset
# variable in it that expands to "/") would take unrelated data with it — and
# --yes removes the one prompt that might have caught it. So every deletion
# target is canonicalized and checked against the places it must never be
# before anything is removed.
assert_safe_target() {
    local label="$1" path="$2" resolved parent
    [ -n "$path" ] || die "$label resolves to an empty path — refusing to delete."
    case "$path" in
        /*) ;;
        *) die "$label must be an absolute path, got '$path' — refusing to delete." ;;
    esac
    # Canonicalize so symlinks and '..' cannot smuggle the target elsewhere.
    # The directory may legitimately be gone already; resolve the deepest
    # existing ancestor then and re-append the rest. This function must ALWAYS
    # print a path or die: returning success silently left the caller with an
    # empty variable, and the `pgrep -f "$METAL_VENV/bin/vllm"` below then
    # degraded to the substring "/bin/vllm", which matches unrelated vLLM
    # processes anywhere on the machine.
    if [ -d "$path" ]; then
        resolved="$(cd "$path" 2>/dev/null && pwd -P)" || die "Cannot resolve $label ('$path')."
    else
        local missing="" probe="$path"
        while [ "$probe" != "/" ] && [ ! -d "$probe" ]; do
            missing="$(basename "$probe")${missing:+/$missing}"
            probe="$(dirname "$probe")"
        done
        resolved="$(cd "$probe" 2>/dev/null && pwd -P)" || die "Cannot resolve $label ('$path')."
        resolved="${resolved%/}/$missing"
    fi
    case "$resolved" in
        /|/Users|/Users/*/|/System*|/Library*|/Applications*|/bin*|/usr*|/etc*|/var*|/opt|/opt/homebrew*)
            die "$label resolves to '$resolved', which is not a Logos worker directory — refusing to delete." ;;
    esac
    [ "$resolved" != "$HOME" ] || die "$label resolves to your home directory — refusing to delete."
    # An ancestor of $HOME would take the home directory with it.
    case "$HOME/" in
        "$resolved"/*) die "$label ('$resolved') contains your home directory — refusing to delete." ;;
    esac
    # Guard against a path so shallow it cannot be a dedicated install dir
    # (/foo). Real targets sit at least two levels deep, e.g. /Users/x/y.
    [ "$(printf '%s' "$resolved" | awk -F/ '{print NF-1}')" -ge 3 ] \
        || die "$label ('$resolved') is too close to the filesystem root to be a worker directory — refusing to delete."
    printf '%s' "$resolved"
}

INSTALL_ROOT="$(assert_safe_target 'LOGOS_MLX_HOME' "$INSTALL_ROOT")" || exit 1
METAL_VENV="$(assert_safe_target 'LOGOS_METAL_VENV' "$METAL_VENV")" || exit 1
# They must not overlap either: removing one would then remove part of the
# other mid-run, leaving the second pass operating on a half-deleted tree.
case "$METAL_VENV/" in
    "$INSTALL_ROOT"/*) : ;;   # venv inside the install root is fine, it goes anyway
    *) case "$INSTALL_ROOT/" in
           "$METAL_VENV"/*) die "LOGOS_MLX_HOME lies inside LOGOS_METAL_VENV — refusing to delete." ;;
       esac ;;
esac

# ── What is actually here ────────────────────────────────────────────────────
# Report before removing: an uninstaller that prints nothing and deletes
# everything is impossible to sanity-check before pressing enter.
present=0
echo
log "About to remove:"
if launchctl print "gui/$(id -u)/$LAUNCH_AGENT_LABEL" >/dev/null 2>&1; then
    echo "    launchd agent    $LAUNCH_AGENT_LABEL (running)"
    present=1
elif [ -f "$LAUNCH_AGENT_PLIST" ]; then
    echo "    launchd agent    $LAUNCH_AGENT_PLIST (not loaded)"
    present=1
fi
if [ -d "$INSTALL_ROOT" ]; then
    size="$(du -sh "$INSTALL_ROOT" 2>/dev/null | cut -f1 || echo '?')"
    if [ "$KEEP_CACHE" -eq 1 ]; then
        echo "    install root     $INSTALL_ROOT ($size, cache/ kept)"
    else
        echo "    install root     $INSTALL_ROOT ($size, including config.yml, .env and cache/)"
    fi
    present=1
fi
if [ -d "$METAL_VENV" ]; then
    echo "    vllm-metal venv  $METAL_VENV ($(du -sh "$METAL_VENV" 2>/dev/null | cut -f1 || echo '?'))"
    present=1
fi
if command -v docker >/dev/null 2>&1 && [ -n "$(docker images -q "$IMAGE" 2>/dev/null)" ]; then
    echo "    docker image     $IMAGE"
    present=1
fi
if [ "$KEEP_POWER" -eq 0 ]; then
    echo "    power settings   restore sleep defaults (needs sudo; see --keep-power-settings)"
fi
if [ "$present" -eq 0 ]; then
    echo "    nothing — no Logos worker node found at these paths."
    echo
    exit 0
fi
echo

if [ "$ASSUME_YES" -eq 0 ]; then
    printf 'Continue? [y/N] '
    read -r reply
    case "$reply" in [yY]*) ;; *) die "Aborted." ;; esac
fi

# ── 1. Stop the agent ────────────────────────────────────────────────────────
# Before deleting files: a live worker forks `vllm serve` children, and pulling
# the venv out from under a running lane leaves orphaned processes holding
# unified memory.
if launchctl print "gui/$(id -u)/$LAUNCH_AGENT_LABEL" >/dev/null 2>&1; then
    log "Stopping the worker"
    launchctl bootout "gui/$(id -u)/$LAUNCH_AGENT_LABEL" 2>/dev/null || true
    # bootout returns before the children are reaped; give the lanes a moment
    # to exit on their own before checking.
    sleep 2
fi
if pgrep -f "$METAL_VENV/bin/vllm" >/dev/null 2>&1; then
    warn "Lane processes still running — terminating them"
    pkill -f "$METAL_VENV/bin/vllm" 2>/dev/null || true
    sleep 1
fi
rm -f "$LAUNCH_AGENT_PLIST"

# ── 2. Remove the installation ───────────────────────────────────────────────
if [ -d "$INSTALL_ROOT" ]; then
    if [ "$KEEP_CACHE" -eq 1 ] && [ -d "$INSTALL_ROOT/cache" ]; then
        log "Removing $INSTALL_ROOT (keeping cache/)"
        # Move the cache aside rather than deleting around it: a find -delete
        # over a 15 GB tree is slow and easy to get wrong. The window between
        # the two moves is the risky part — an interrupt there would strand
        # tens of GB in a temp directory the operator never hears about — so
        # the staged copy is put back on any abnormal exit until the final
        # move has succeeded.
        staged="$(mktemp -d "${TMPDIR:-/tmp}/logos-mlx-cache.XXXXXX")"
        restore_cache() {
            [ -d "$staged/cache" ] || return 0
            warn "Interrupted — restoring the staged cache to $INSTALL_ROOT/cache"
            mkdir -p "$INSTALL_ROOT"
            mv "$staged/cache" "$INSTALL_ROOT/cache" 2>/dev/null \
                || warn "  could not restore it automatically; it is in $staged/cache"
            rmdir "$staged" 2>/dev/null || true
        }
        trap 'restore_cache' EXIT INT TERM
        mv "$INSTALL_ROOT/cache" "$staged/cache"
        rm -rf "$INSTALL_ROOT"
        mkdir -p "$INSTALL_ROOT"
        mv "$staged/cache" "$INSTALL_ROOT/cache"
        rmdir "$staged"
        trap - EXIT INT TERM
        log "  kept $INSTALL_ROOT/cache"
    else
        log "Removing $INSTALL_ROOT"
        rm -rf "$INSTALL_ROOT"
    fi
fi

[ -d "$METAL_VENV" ] && { log "Removing $METAL_VENV"; rm -rf "$METAL_VENV"; }

if command -v docker >/dev/null 2>&1 && [ -n "$(docker images -q "$IMAGE" 2>/dev/null)" ]; then
    log "Removing docker image $IMAGE"
    docker images --format '{{.Repository}}:{{.Tag}}' \
        | grep -E "^$(printf '%s' "$IMAGE" | sed 's/[].[^$\\*/]/\\&/g'):" \
        | xargs -r -n1 docker rmi >/dev/null 2>&1 || true
fi

# ── 3. Power settings ────────────────────────────────────────────────────────
# The install guide turns sleep off so a closed-lid MacBook keeps serving.
# Leaving a decommissioned laptop unable to sleep drains it flat, so restore
# the defaults unless asked not to.
if [ "$KEEP_POWER" -eq 0 ]; then
    if [ "$(pmset -g 2>/dev/null | awk '/SleepDisabled/ {print $2}')" = "1" ]; then
        log "Restoring sleep defaults (sudo)"
        sudo pmset -a disablesleep 0 || warn "Could not restore disablesleep — run: sudo pmset -a disablesleep 0"
        # Mirror every knob bootstrap-macos.sh turns off, standby and
        # autopoweroff included — leaving those at 0 keeps the deeper
        # power-saving states disabled long after the worker is gone.
        sudo pmset -c sleep 10 displaysleep 10 disksleep 10 standby 1 autopoweroff 1 powernap 1 \
            || warn "Could not restore AC sleep settings — check 'pmset -g custom'"
    fi
fi

log "Done."
echo
echo "Left in place on purpose:"
echo "  ~/.cache/huggingface   your own HF cache (the worker's models lived under the install root)"
echo "  Homebrew, uv, python   prerequisites shared with other tools"
echo
echo "The provider entry in Logos is server-side state — remove it in the UI"
echo "if this node is gone for good, otherwise it lingers as permanently"
echo "disconnected."
