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
#   ghcr.io/ls1intum/edutelligence/logos-workernode-mlx                  the pulled image
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
IMAGE="${LOGOS_MLX_IMAGE:-ghcr.io/ls1intum/edutelligence/logos-workernode-mlx}"
LAUNCH_AGENT_LABEL="de.tum.logos.workernode"
LAUNCH_AGENT_PLIST="$HOME/Library/LaunchAgents/$LAUNCH_AGENT_LABEL.plist"
# Written by bootstrap-macos.sh before it changes the power settings, and
# deliberately outside the install root so it survives the removal below.
POWER_STATE_DIR="$HOME/Library/Application Support/$LAUNCH_AGENT_LABEL"
POWER_STATE_FILE="$POWER_STATE_DIR/power-state.saved"

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
    [ "$resolved" != "/" ] || die "$label resolves to '/' — refusing to delete."
    [ "$resolved" != "/Users" ] || die "$label resolves to '/Users' — refusing to delete."

    # Compare against the CANONICAL form of each system tree, not its spelling.
    # Literal prefixes are a trap on macOS: /etc, /var and /tmp are symlinks
    # into /private, so canonicalizing first (which the code above must do, to
    # stop symlinks smuggling the target elsewhere) turns LOGOS_MLX_HOME=/etc/ssh
    # into /private/etc/ssh — which matched no literal prefix, passed the depth
    # check, and would have been deleted. Resolving the forbidden roots the same
    # way closes that gap by construction instead of by listing every alias.
    for sys_root in /System /Library /Applications /bin /sbin /usr /etc /var /tmp /opt /private /cores /Network /Volumes; do
        canon_root="$(cd "$sys_root" 2>/dev/null && pwd -P)" || continue
        if [ "$resolved" = "$canon_root" ]; then
            die "$label resolves to the system directory '$resolved' — refusing to delete."
        fi
        case "$resolved/" in
            "$canon_root"/*)
                die "$label resolves to '$resolved', inside the system tree $sys_root ($canon_root) — refusing to delete." ;;
        esac
    done
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
# Outstanding power changes count as something to do in their own right. They
# outlive the files: an interrupted uninstall, or a pmset call that failed the
# first time, leaves a Mac that cannot sleep — and if this branch returned
# early just because the directories are already gone, re-running the script
# could never put that right.
#
# Checking SleepDisabled alone is not enough: the bootstrap sets it AND zeroes
# six AC timers, in two separate pmset calls. If the first succeeds and the
# second fails, SleepDisabled reads 0 while sleep/standby/powernap are still
# pinned at 0 — a rerun would see nothing pending and exit, with no way left
# to restore them. Look at both halves.
power_changes_pending() {
    [ "$KEEP_POWER" -eq 0 ] || return 1
    # The recording the bootstrap wrote before changing anything is the ONLY
    # evidence of ownership, disablesleep included. A machine can arrive with
    # sleep already disabled by an operator or an MDM policy — and in that
    # case the bootstrap returns early without writing a record, precisely so
    # that removing the worker does not undo a policy it never set. Likewise a
    # zeroed timer proves nothing on its own: plenty of Macs legitimately run
    # with powernap or disksleep at 0.
    [ -s "$POWER_STATE_FILE" ]
}
POWER_PENDING=0
if power_changes_pending; then
    POWER_PENDING=1
fi
if [ "$POWER_PENDING" -eq 1 ]; then
    echo "    power settings   restoring what the bootstrap changed (needs sudo; see --keep-power-settings)"
    present=1
fi
if [ "$present" -eq 0 ]; then
    echo "    nothing — no Logos worker node found at these paths, and sleep is not disabled."
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
# -f matches against a REGEX, not a literal string, and the path is full of
# metacharacters — even the default $HOME/.venv-vllm-metal has a `.` that
# matches any character, so a process at $HOME/Xvenv-vllm-metal/bin/vllm would
# be killed too. Escape everything that means something to the regex engine.
#
# Match at an argument boundary, NOT at byte zero: `vllm` is a Python console
# script, so once its shebang is resolved the command line reads
# "<venv>/bin/python <venv>/bin/vllm serve …" and the script path is an
# argument, not the start of the line. Anchoring at ^ missed exactly the
# orphaned lanes this is here to catch — they would survive `bootout` and then
# have their venv deleted underneath them. The boundary still prevents a
# mid-path match such as /elsewhere/<venv>/bin/vllm.
metal_vllm_escaped="$(printf '%s' "$METAL_VENV/bin/vllm" | sed 's/[][\\.^$*+?(){}|\/]/\\&/g')"
metal_vllm_pattern="(^|[[:space:]])${metal_vllm_escaped}([[:space:]]|$)"
if pgrep -f "$metal_vllm_pattern" >/dev/null 2>&1; then
    warn "Lane processes still running — terminating them"
    pkill -f "$metal_vllm_pattern" 2>/dev/null || true
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
        # EXIT restores; INT/TERM restore AND leave. Bash resumes the script
        # after a signal handler that does not exit, so a Ctrl-C landing
        # between the two moves below would put the cache back and then walk
        # straight into `rm -rf "$INSTALL_ROOT"` — deleting exactly what was
        # just rescued.
        trap 'restore_cache' EXIT
        trap 'restore_cache; exit 130' INT
        trap 'restore_cache; exit 143' TERM
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
        | xargs -n1 docker rmi >/dev/null 2>&1 || true
    # No -r: BSD xargs does not run the command on empty input anyway, and
    # the flag is a GNU extension this script has no reason to depend on.
fi

# ── 3. Power settings ────────────────────────────────────────────────────────
# The install guide turns sleep off so a closed-lid MacBook keeps serving.
# Leaving a decommissioned laptop unable to sleep drains it flat, so restore
# the defaults unless asked not to.
if [ "$KEEP_POWER" -eq 0 ]; then
    # Re-read rather than trusting POWER_PENDING from the summary above: the
    # removal steps in between take time, and this is the check that decides
    # whether sudo is asked for at all. Both halves again, so a previously
    # half-completed restore is finished rather than skipped.
    if power_changes_pending; then
        log "Restoring power settings (sudo)"
        # Every field comes from the record, disablesleep included — nothing is
        # reset that Logos cannot prove it changed.
        if [ -s "$POWER_STATE_FILE" ]; then
            # The record may only be discarded once EVERY field it describes is
            # back. Deleting it after a partial success would strand the rest:
            # the next run finds no record, concludes Logos owns nothing, and
            # leaves the machine on the settings the worker imposed with no way
            # left to undo them.
            restore_ok=1
            saved_disablesleep="$(awk '$1 == "disablesleep" {print $2}' "$POWER_STATE_FILE")"
            case "$saved_disablesleep" in
                0|1)
                    sudo pmset -a disablesleep "$saved_disablesleep" \
                        || { restore_ok=0
                             warn "Could not restore disablesleep — run: sudo pmset -a disablesleep $saved_disablesleep"; } ;;
                *) warn "No disablesleep value recorded; leaving it as it is." ;;
            esac
            restore_args=""
            while read -r field value; do
                case "$field" in
                    sleep|displaysleep|disksleep|standby|autopoweroff|powernap)
                        case "$value" in
                            ''|*[!0-9]*) continue ;;
                        esac
                        restore_args="$restore_args $field $value" ;;
                esac
            done < "$POWER_STATE_FILE"
            if [ -n "$restore_args" ]; then
                # shellcheck disable=SC2086 -- deliberate word splitting into pmset arguments
                if sudo pmset -c $restore_args; then
                    log "  restored:$restore_args"
                else
                    restore_ok=0
                    warn "Could not restore the AC settings — check 'pmset -g custom'"
                fi
            fi
            if [ "$restore_ok" -eq 1 ]; then
                rm -f "$POWER_STATE_FILE"
                # A partial from an interrupted bootstrap attempt would keep
                # the directory alive; it is inert, but there is no reason to
                # leave it behind once everything is restored.
                rm -f "$POWER_STATE_DIR"/power-state.partial.*
                rmdir "$POWER_STATE_DIR" 2>/dev/null || true
            else
                warn "  keeping $POWER_STATE_FILE so the restore can be retried by re-running this script"
            fi
        else
            log "  no recording from the bootstrap; left the power settings untouched"
        fi
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
