#!/usr/bin/env bash
#
# claude-logos — run Claude Code against a Logos gateway instead of api.anthropic.com.
#
# Logos serves the Anthropic Messages API natively at POST /v1/messages, so there is no
# proxy in between: Claude Code talks to Logos directly.
#
#   claude-logos                      interactive session
#   claude-logos -p "..."             headless / one-shot
#   claude-logos --resume             every claude flag is passed through unchanged
#
#   claude-logos --check              show the connection, the model and how much
#                                     context this session would get, then exit
#   claude-logos --install            install to ~/.local/bin (reads config from stdin)
#   claude-logos --update             replace this wrapper with the current one
#   claude-logos --uninstall          remove the wrapper, its config and its key
#   claude-logos --help               this text, then claude's own
#
# NOTHING OUTSIDE THIS WRAPPER IS TOUCHED. The Logos credential, base URL and model are
# exported into the child process only, and the extra Claude Code settings live in this
# wrapper's own directory and are handed over with --settings. Your shell profile,
# ~/.claude/settings.json and your claude.ai login are left exactly as they are, so plain
# `claude` keeps using your Anthropic subscription with no reconfiguration.
#
# It never updates itself either. It notices when Logos serves a newer revision and
# says so; replacing it is always something you type.
#
# This file is served by the Logos UI at <logos-url>/claude-logos.sh and is what the
# "AI Tools" page installs.
#
set -euo pipefail

# Bump on every change installed copies should pick up. A monotonic integer, not a
# version string: the comparison is a single `-gt` that cannot misread anything,
# where sorting "1.10" against "1.9" needs care to get right. The date is here for
# people; only the number is compared.
CLAUDE_LOGOS_VERSION=2          # 2026-09-04

CONFIG_DIR="${LOGOS_CONFIG_DIR:-$HOME/.config/claude-logos}"
CONFIG_FILE="$CONFIG_DIR/config"
KEY_FILE_DEFAULT="$CONFIG_DIR/key"
SETTINGS_FILE_DEFAULT="$CONFIG_DIR/settings.json"
INSTALL_PATH="${LOGOS_INSTALL_PATH:-$HOME/.local/bin/claude-logos}"
# Two files this wrapper keeps between runs. Declared here with the rest of the
# paths rather than next to the code that uses them: --uninstall runs before that
# code is reached, and under `set -u` an undeclared name is a hard error.
KNOWN_MODELS_FILE="$CONFIG_DIR/known-models"
VERSION_STATE_FILE="$CONFIG_DIR/latest-revision"

# ── Settings, lowest precedence first ───────────────────────────────────────────
# The config file is written by --install (i.e. by the AI Tools page) and holds
# KEY=value lines. Environment variables win over it so a single invocation can be
# redirected without editing anything:
#
#   LOGOS_MODEL=openai/gpt-oss-120b claude-logos
#
if [[ -r "$CONFIG_FILE" ]]; then
  # Read as data, not as shell: a stray backtick or $(...) in a value must not run.
  while IFS='=' read -r config_name config_value; do
    [[ "$config_name" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
    [[ -n "${!config_name:-}" ]] && continue   # already set in the environment
    printf -v "$config_name" '%s' "$config_value"
    export "${config_name?}"
  done < <(grep -E '^[A-Z_][A-Z0-9_]*=' "$CONFIG_FILE" || true)
fi

LOGOS_URL="${LOGOS_URL:-https://logos.aet.cit.tum.de}"
LOGOS_URL="${LOGOS_URL%/}"
LOGOS_MODEL="${LOGOS_MODEL:-}"
LOGOS_KEY_FILE="${LOGOS_KEY_FILE:-$KEY_FILE_DEFAULT}"
LOGOS_SETTINGS="${LOGOS_SETTINGS-$SETTINGS_FILE_DEFAULT}"

# Which context size to run the session at. Logos reports three:
#
#   available   what Logos can give this model at the moment. The default, and the
#               reason for asking Logos at startup instead of hardcoding a number:
#               long requests are sent wherever there is room for them.
#   guaranteed  the size you get whatever the load. Never turned down, at the cost
#               of compacting earlier than necessary. Switch to this if you ever see
#               a request rejected for being too long.
#   max         the most this model can ever offer. Optimistic: it needs capacity to
#               be free at the time you use it.
LOGOS_CONTEXT_SOURCE="${LOGOS_CONTEXT_SOURCE:-available}"

# Fallback window for a model the gateway reports no window for (cloud models, or a
# lane the worker has not reported yet). Deliberately small: too small only compacts
# early, too large sends requests the worker rejects.
LOGOS_CONTEXT_FALLBACK="${LOGOS_CONTEXT_FALLBACK:-111200}"

# Claude Code caps what it reserves for output at 20000 tokens no matter how large a
# CLAUDE_CODE_MAX_OUTPUT_TOKENS it is given, and it subtracts that reservation from the
# window itself (vLLM charges input and output against one budget, so that is correct).
# Asking for more than the cap therefore buys nothing and costs context — see the
# arithmetic printed by --check.
#
# Lowering it is the one knob that makes a narrow window usable: on a window under
# ~37000 tokens the default leaves less input room than Claude Code's own opening
# prompt, and the session is refused before it starts (see the floor check below,
# which prints the value that would fit).
LOGOS_MAX_OUTPUT_TOKENS="${LOGOS_MAX_OUTPUT_TOKENS:-20000}"

# Safety margin taken off the window before Claude Code is told about it. Claude Code
# estimates tokens with its own tokenizer, which runs slightly under what the worker's
# tokenizer counts, so a request can slip past the real input cap and come back as a
# 400. Scales with the window and is clamped: small windows cannot afford a fixed cut,
# large ones do not need more.
LOGOS_CONTEXT_HEADROOM="${LOGOS_CONTEXT_HEADROOM:-}"

# Claude Code puts its reasoning effort in every request as output_config.effort. Logos
# rejects the value "high" outright — "Unexpected reasoning effort high. Supported types
# are xhigh (default), medium, and low" — with HTTP 500, before the model sees anything,
# so a session left on high fails on every turn, including a bare "hello". Verified
# against a real 59-tool request: xhigh, medium and low all return 200, only high does
# not. xhigh is the closest to Claude Code's default rather than a step down in depth.
# Applied as the --effort flag: the CLAUDE_CODE_EFFORT environment variable does NOT
# override what lands in output_config (measured — requests still carried "high" with it
# set). Set LOGOS_EFFORT= (empty) to opt out once Logos accepts "high".
LOGOS_EFFORT="${LOGOS_EFFORT:-xhigh}"

die() { printf 'claude-logos: %s\n' "$1" >&2; exit "${2:-1}"; }
note() { printf 'claude-logos: %s\n' "$1" >&2; }

usage() {
  # Every comment line of the header block, so adding a line up there cannot
  # silently fall out of --help the way a fixed line range would.
  awk 'NR > 2 && /^#/ { sub(/^# ?/, ""); print; next } NR > 2 { exit }' "$0"
  printf 'revision: %s\n' "$CLAUDE_LOGOS_VERSION"
}

# ── Revision check ──────────────────────────────────────────────────────────────
# Logos serves the current wrapper at the same URL this copy came from, so the
# revision in that file is the only source of truth — there is no second place to
# keep in sync and therefore no way for the two to disagree.
#
# Nothing here ever replaces this script. The check runs in the background and
# writes what it found to a file; the *next* start reads that file and says so.
# Two consequences, both deliberate:
#
#   * startup is never slower for it, even on a slow or captive network
#   * a new revision is announced one start after it appears, which is soon
#     enough for something the user then has to act on by hand anyway
VERSION_CHECK_INTERVAL_SECONDS="${LOGOS_VERSION_CHECK_INTERVAL:-86400}"

remote_revision_from() {
  # Only a bare `CLAUDE_LOGOS_VERSION=<digits>` assignment counts, so the line in
  # this very comment block cannot be mistaken for the declaration.
  sed -n 's/^CLAUDE_LOGOS_VERSION=\([0-9][0-9]*\).*/\1/p' "$1" | head -1
}

report_new_revision() {
  [[ -r "$VERSION_STATE_FILE" ]] || return 0
  local latest checked
  IFS=$'\t' read -r latest checked < "$VERSION_STATE_FILE" || return 0
  [[ "$latest" =~ ^[0-9]+$ ]] || return 0
  (( latest > CLAUDE_LOGOS_VERSION )) || return 0
  printf 'update   : claude-logos revision %s is available (this is %s)\n' \
    "$latest" "$CLAUDE_LOGOS_VERSION"
  printf '           run: claude-logos --update    (nothing changes until you do)\n'
}

refresh_latest_revision() {
  local now age=$(( VERSION_CHECK_INTERVAL_SECONDS + 1 ))
  now="$(date +%s)"
  if [[ -r "$VERSION_STATE_FILE" ]]; then
    local _latest checked
    IFS=$'\t' read -r _latest checked < "$VERSION_STATE_FILE" || checked=""
    [[ "$checked" =~ ^[0-9]+$ ]] && age=$(( now - checked ))
  fi
  (( age <= VERSION_CHECK_INTERVAL_SECONDS )) && return 0
  {
    local body remote
    body="$(mktemp)" || exit 0
    if curl -fsS -m 20 "$LOGOS_URL/claude-logos.sh" -o "$body" 2>/dev/null; then
      remote="$(remote_revision_from "$body")"
      [[ -n "$remote" ]] && printf '%s\t%s\n' "$remote" "$now" > "$VERSION_STATE_FILE"
    fi
    rm -f "$body"
  } >/dev/null 2>&1 &
}

# ── --update ────────────────────────────────────────────────────────────────────
# Replaces this file and nothing else: the key, the config and the settings layer
# stay as they are, so an update is not a re-setup and the Logos web UI does not
# have to be visited again.
logos_update() {
  local target="$INSTALL_PATH"
  [[ -e "$target" ]] || target="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

  # Same directory as the target, so the final move is a rename within one
  # filesystem — atomic, and it cannot half-write the wrapper.
  local staged
  staged="$(mktemp "$(dirname "$target")/claude-logos.XXXXXX")" ||
    die "could not write next to $target"
  # shellcheck disable=SC2064  # $staged is fixed at this point; expand it now.
  trap "rm -f '$staged'" EXIT

  curl -fsS -m 60 "$LOGOS_URL/claude-logos.sh" -o "$staged" ||
    die "could not download $LOGOS_URL/claude-logos.sh"

  # Validate before replacing anything. A captive portal, a proxy error page or a
  # truncated transfer would otherwise leave a working wrapper overwritten with
  # HTML — and the next thing the user runs is this file.
  local remote
  remote="$(remote_revision_from "$staged")"
  [[ -n "$remote" ]] || die "what $LOGOS_URL served is not a claude-logos script"
  bash -n "$staged" 2>/dev/null || die "the downloaded script does not parse — not installing it"

  if (( remote == CLAUDE_LOGOS_VERSION )); then
    printf 'Already current (revision %s).\n' "$CLAUDE_LOGOS_VERSION"
    rm -f "$VERSION_STATE_FILE"
    return 0
  fi

  chmod 755 "$staged"
  mv -f "$staged" "$target" || die "could not replace $target"
  trap - EXIT
  # mv swapped the inode, so this still-running copy keeps reading the old file
  # and finishes normally; the next invocation is the new one.
  rm -f "$VERSION_STATE_FILE"
  printf 'Updated %s: revision %s → %s\n' "$target" "$CLAUDE_LOGOS_VERSION" "$remote"
  printf 'Your key, model and settings were not touched.\n'
}

# ── --install ───────────────────────────────────────────────────────────────────
# Reads KEY=value lines from stdin so the Logos key never appears in the process
# list or the shell history of a `ps`-visible command line.
logos_install() {
  local url="" model="" key="" name value
  while IFS='=' read -r name value; do
    case "$name" in
      LOGOS_URL) url="$value" ;;
      LOGOS_MODEL) model="$value" ;;
      LOGOS_KEY) key="$value" ;;
    esac
  done
  [[ -n "$key" ]] || die "--install needs a LOGOS_KEY=… line on stdin"
  [[ -n "$url" ]] || die "--install needs a LOGOS_URL=… line on stdin"

  mkdir -p "$(dirname "$INSTALL_PATH")" "$CONFIG_DIR"
  chmod 700 "$CONFIG_DIR"

  # Copy this script rather than symlink it: the download it came from is a temp file.
  if [[ "$(cd "$(dirname "$0")" && pwd)/$(basename "$0")" != "$INSTALL_PATH" ]]; then
    cat "$0" > "$INSTALL_PATH"
  fi
  chmod 755 "$INSTALL_PATH"

  ( umask 177; printf '%s\n' "${key//[$'\r\n']/}" > "$LOGOS_KEY_FILE" )

  { printf '# Written by claude-logos --install. Environment variables win over this file.\n'
    printf 'LOGOS_URL=%s\n' "${url%/}"
    [[ -n "$model" ]] && printf 'LOGOS_MODEL=%s\n' "$model"
  } > "$CONFIG_FILE"
  chmod 600 "$CONFIG_FILE"

  # WebSearch is a server-side Anthropic tool: when the model invokes it, Claude Code
  # sends a request whose tools array holds {"type":"web_search_20250305"} with no
  # input_schema. vLLM on the Logos worker nodes requires input_schema on every tool
  # and rejects that with 400, which Claude Code then retries in a loop. Denying the
  # tool keeps it out of the request entirely. A separate settings layer rather than
  # --disallowedTools, so it does not clash with that flag when you pass it yourself,
  # and a separate FILE so ~/.claude/settings.json stays untouched.
  cat > "$SETTINGS_FILE_DEFAULT" <<'SETTINGS'
{
  "permissions": {
    "deny": ["WebSearch"]
  }
}
SETTINGS
  chmod 600 "$SETTINGS_FILE_DEFAULT"

  printf 'Installed:\n'
  printf '  %s\n' "$INSTALL_PATH"
  printf '  %s (key, mode 600)\n' "$LOGOS_KEY_FILE"
  printf '  %s\n' "$CONFIG_FILE"
  printf '  %s\n' "$SETTINGS_FILE_DEFAULT"
  printf '\nNothing else on this machine was modified — plain `claude` still uses your\n'
  printf 'Anthropic subscription.\n\n'

  case ":$PATH:" in
    *":$(dirname "$INSTALL_PATH"):"*)
      printf 'Run: claude-logos\n' ;;
    *)
      printf '%s is not on your PATH yet. Add it:\n\n' "$(dirname "$INSTALL_PATH")"
      printf '  echo '\''export PATH="$HOME/.local/bin:$PATH"'\'' >> %s\n\n' "$(login_profile)"
      printf 'Then open a new terminal and run: claude-logos\n' ;;
  esac
}

login_profile() {
  # Printed for the user to read, so the literal tilde is the point.
  # shellcheck disable=SC2088
  case "$(basename "${SHELL:-bash}")" in
    zsh) printf '~/.zshrc' ;;
    fish) printf '~/.config/fish/config.fish' ;;
    *) printf '~/.bashrc' ;;
  esac
}

# ── --uninstall ─────────────────────────────────────────────────────────────────
logos_uninstall() {
  local assume_yes="${1:-no}" removed=0

  # The AI Tools page used to configure Claude Code by writing an env block into
  # ~/.claude/settings.json. That predates this wrapper, and leaving it behind would
  # keep pointing plain `claude` at Logos after an uninstall — the opposite of
  # "removed". Offer to clean it, but only when it really is the Logos block.
  local user_settings="$HOME/.claude/settings.json"
  local stale_keys=""
  if [[ -r "$user_settings" ]] && command -v python3 >/dev/null 2>&1; then
    stale_keys="$(python3 - "$user_settings" "$LOGOS_URL" <<'PY'
import json, sys
path, logos_url = sys.argv[1], sys.argv[2].rstrip("/")
try:
    with open(path) as fh:
        cfg = json.load(fh)
except Exception:
    sys.exit(0)
env = cfg.get("env")
if not isinstance(env, dict):
    sys.exit(0)
base = str(env.get("ANTHROPIC_BASE_URL", "")).rstrip("/")
# Only claim the block when it actually points at a Logos gateway. A user who put
# their own ANTHROPIC_BASE_URL there keeps it.
if not base or (base != logos_url and "logos" not in base.lower()):
    sys.exit(0)
managed = [
    "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL", "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
]
print(" ".join(k for k in managed if k in env))
PY
)" || stale_keys=""
  fi

  if [[ -n "${stale_keys// /}" ]]; then
    printf 'Found an older Logos env block in %s:\n' "$user_settings"
    printf '  %s\n' $stale_keys
    printf 'It points plain `claude` at Logos, so leaving it keeps the setup half-installed.\n'
    if [[ "$assume_yes" != "yes" ]]; then
      if [[ -t 0 ]]; then
        read -r -p 'Remove those keys? [y/N] ' answer
        [[ "$answer" == [yY]* ]] && assume_yes="yes"
      else
        note "not a terminal — re-run with --uninstall --yes to remove them too"
      fi
    fi
    if [[ "$assume_yes" == "yes" ]]; then
      python3 - "$user_settings" $stale_keys <<'PY'
import json, sys
path, keys = sys.argv[1], sys.argv[2:]
with open(path) as fh:
    cfg = json.load(fh)
env = cfg.get("env", {})
for key in keys:
    env.pop(key, None)
if not env:
    cfg.pop("env", None)
perms = cfg.get("permissions")
if isinstance(perms, dict) and isinstance(perms.get("deny"), list):
    perms["deny"] = [t for t in perms["deny"] if t != "WebSearch"]
    if not perms["deny"]:
        perms.pop("deny")
    if not perms:
        cfg.pop("permissions", None)
with open(path, "w") as fh:
    json.dump(cfg, fh, indent=2)
    fh.write("\n")
PY
      printf '  cleaned %s\n' "$user_settings"
      removed=1
    fi
  fi

  for path in "$LOGOS_KEY_FILE" "$SETTINGS_FILE_DEFAULT" "$CONFIG_FILE" \
    "$KNOWN_MODELS_FILE" "$VERSION_STATE_FILE"; do
    if [[ -e "$path" ]]; then
      rm -f "$path"
      printf '  removed %s\n' "$path"
      removed=1
    fi
  done
  # Only when empty: never take a directory the user put other things in.
  if [[ -d "$CONFIG_DIR" ]] && [[ -z "$(ls -A "$CONFIG_DIR")" ]]; then
    rmdir "$CONFIG_DIR"
    printf '  removed %s\n' "$CONFIG_DIR"
    removed=1
  elif [[ -d "$CONFIG_DIR" ]]; then
    note "kept $CONFIG_DIR — it still holds files this wrapper did not create"
  fi
  for path in "$INSTALL_PATH" "$HOME/.local/bin/claude-logos"; do
    if [[ -e "$path" ]]; then
      rm -f "$path"
      printf '  removed %s\n' "$path"
      removed=1
    fi
  done

  if (( removed )); then
    printf '\nDone. Nothing of claude-logos is left; `claude` is unaffected.\n'
  else
    printf 'Nothing to remove — claude-logos is not installed here.\n'
  fi
}

# ── Argument handling ───────────────────────────────────────────────────────────
# Four verbs are ours; everything else goes to claude untouched, which is what
# makes `claude-logos <anything>` behave like `claude <anything>`.
#
# --help is the one overlap: `claude --help` is a real command. So we print this
# wrapper's own help and then hand over to claude's, which is what someone typing
# it actually wants — both halves of what `claude-logos` can do.
case "${1:-}" in
  --help|-h)
    usage
    printf '\n── claude'"'"'s own options ──────────────────────────────────────────\n\n'
    exec claude --help
    ;;
  --install) shift; logos_install; exit 0 ;;
  --update) shift; logos_update; exit 0 ;;
  --uninstall)
    shift
    assume_yes="no"
    [[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]] && assume_yes="yes"
    logos_uninstall "$assume_yes"
    exit 0
    ;;
esac

# ── Credential ──────────────────────────────────────────────────────────────────
if [[ ! -r "$LOGOS_KEY_FILE" ]]; then
  die "no readable key at $LOGOS_KEY_FILE
  Install from the Logos web UI (AI Tools → Claude Code), or write one by hand:
    install -m 600 /dev/null '$LOGOS_KEY_FILE' && printf %s '<logos-key>' > '$LOGOS_KEY_FILE'"
fi
# tr strips a trailing newline an editor may have added — a newline in the bearer
# token produces a confusing 401.
LOGOS_KEY="$(tr -d '\r\n' < "$LOGOS_KEY_FILE")"
[[ -n "$LOGOS_KEY" ]] || die "the key file $LOGOS_KEY_FILE is empty"

# ── Context window, from the gateway ────────────────────────────────────────────
# The window is not a property of the model, it is a property of the lane serving it:
# the capacity planner gives a lane as much context as the node's free KV cache allows,
# so the same model can run at 262144 tokens on one worker and a fraction of that on
# another, and a re-calibration moves it again. Asking GET /v1/models at startup is one
# cheap metadata call (no GPU work) and it is the only way to be right about a number
# that moves without the model changing.
context_probe() {
  curl -fsS -m 15 "$LOGOS_URL/v1/models" -H "Authorization: Bearer $LOGOS_KEY" 2>/dev/null |
    python3 -c '
import json, sys

model, source = sys.argv[1], sys.argv[2]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
entries = [m for m in data.get("data", []) if isinstance(m, dict)]
served = next((m for m in entries if m.get("id") == model), None)
if served is None:
    # No model pinned, or one this key cannot see: report the known ids so the
    # caller can say something useful instead of failing on a 404 later.
    print("ids\t" + "\t".join(str(m.get("id", "?")) for m in entries))
    sys.exit(0)


def window(field):
    try:
        value = int(served.get(field) or 0)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


# max_model_len is the size that always holds and the one field vLLM itself
# uses; the *_current_* and *_overall* names are Logos extensions. Older Logos
# versions send only the first, so every step falls back to the one below it.
guaranteed = window("max_model_len_current_min") or window("max_model_len")
available = window("max_model_len_current_max") or guaranteed
maximum = window("max_model_len_overall") or available
chosen = {
    "guaranteed": guaranteed,
    "available": available,
    "max": maximum,
}.get(source, available) or guaranteed
# Nothing is serving the model right now: the current_* pair only exists while a
# lane is up, so both are empty and the cascade above has nothing to hand back.
# max_model_len_overall comes from the model profile instead and survives that,
# so it is still known — and it beats the blind fallback constant, which is a
# guess for every model at once and is wrong in both directions (way under a
# 262144-token model, way over a 32768-token one).
chosen = chosen or maximum
print(f"window\t{chosen}\t{guaranteed}\t{available}\t{maximum}")
' "$LOGOS_MODEL" "$LOGOS_CONTEXT_SOURCE" || true
}

# Every model id this key can see, one per line. Used for the "new model
# available" notice below; a separate call would double the startup cost, so
# this reuses the same listing the window came from.
model_ids_probe() {
  curl -fsS -m 15 "$LOGOS_URL/v1/models" -H "Authorization: Bearer $LOGOS_KEY" 2>/dev/null |
    python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for entry in data.get("data", []):
    if isinstance(entry, dict) and entry.get("id"):
        print(entry["id"])
' || true
}

# ── New models since the last run ───────────────────────────────────────────────
# Models get added to a team without anyone telling the people on it. The list is
# already in hand from the call above, so noticing an addition costs one file
# comparison — and the terminal someone is about to work in is the one place they
# will actually read it.
report_new_models() {
  local current="$1" previous=""
  [[ -n "$current" ]] || return 0
  if [[ -r "$KNOWN_MODELS_FILE" ]]; then
    previous="$(cat "$KNOWN_MODELS_FILE")"
  else
    # First run: record the baseline silently rather than announcing every
    # model the team already had as "new".
    printf '%s\n' "$current" > "$KNOWN_MODELS_FILE" 2>/dev/null || true
    return 0
  fi
  local added
  added="$(comm -13 <(printf '%s\n' "$previous" | sort -u) <(printf '%s\n' "$current" | sort -u))"
  if [[ -n "$added" ]]; then
    printf 'new      : %s now available to you\n' "$(printf '%s' "$added" | tr '\n' ' ' | sed 's/ $//')"
    printf '           (set LOGOS_MODEL=<id> to use one, or re-run the setup on the Logos web UI)\n'
  fi
  printf '%s\n' "$current" > "$KNOWN_MODELS_FILE" 2>/dev/null || true
}

# ── Warm-up ─────────────────────────────────────────────────────────────────────
# A session starts, the developer reads the startup line, and the first real
# request lands seconds later — paying for a cold load that could have happened
# during those seconds. This tells Logos the model is about to be used and
# returns immediately; Logos decides what to do with that, and a request is
# never sent on our behalf.
trigger_warmup() {
  curl -fsS -m 5 -o /dev/null -X POST \
    "$LOGOS_URL/v1/models/$LOGOS_MODEL/warmup" \
    -H "Authorization: Bearer $LOGOS_KEY" >/dev/null 2>&1 || true
}

LOGOS_CONTEXT_TOKENS=0
LOGOS_CONTEXT_GUARANTEED=0
LOGOS_CONTEXT_AVAILABLE=0
LOGOS_CONTEXT_MAX=0
CONTEXT_ORIGIN="estimate"
KNOWN_MODEL_IDS=""

if [[ -z "$LOGOS_MODEL" ]]; then
  die "no model configured
  Set one in $CONFIG_FILE (LOGOS_MODEL=…), or per invocation:
    LOGOS_MODEL=<model> claude-logos"
fi

probe_result="$(context_probe)"
case "$probe_result" in
  window*)
    IFS=$'\t' read -r _ LOGOS_CONTEXT_TOKENS LOGOS_CONTEXT_GUARANTEED LOGOS_CONTEXT_AVAILABLE \
      LOGOS_CONTEXT_MAX <<<"$probe_result"
    CONTEXT_ORIGIN="$LOGOS_CONTEXT_SOURCE"
    # No lane is up, so neither current_* figure exists and the probe fell back
    # to the model's own maximum. Worth saying: the session is sized against a
    # window Logos has not committed to yet, not against one it is serving.
    if (( LOGOS_CONTEXT_GUARANTEED <= 0 && LOGOS_CONTEXT_AVAILABLE <= 0 && LOGOS_CONTEXT_MAX > 0 )); then
      CONTEXT_ORIGIN="cold"
    fi
    ;;
  ids*)
    KNOWN_MODEL_IDS="${probe_result#ids}"
    KNOWN_MODEL_IDS="${KNOWN_MODEL_IDS//$'\t'/ }"
    KNOWN_MODEL_IDS="${KNOWN_MODEL_IDS# }"
    ;;
esac

if (( LOGOS_CONTEXT_TOKENS <= 0 )); then
  LOGOS_CONTEXT_TOKENS="$LOGOS_CONTEXT_FALLBACK"
  CONTEXT_ORIGIN="estimate"
fi

if [[ -z "$LOGOS_CONTEXT_HEADROOM" ]]; then
  # ~2% of the window, clamped: enough to absorb tokenizer drift without eating a
  # small window alive.
  LOGOS_CONTEXT_HEADROOM=$(( LOGOS_CONTEXT_TOKENS / 50 ))
  (( LOGOS_CONTEXT_HEADROOM < 1024 )) && LOGOS_CONTEXT_HEADROOM=1024
  (( LOGOS_CONTEXT_HEADROOM > 8192 )) && LOGOS_CONTEXT_HEADROOM=8192
fi

# The number handed to Claude Code is the window MINUS the headroom and nothing else.
# Claude Code subtracts its own output reservation — min(CLAUDE_CODE_MAX_OUTPUT_TOKENS,
# 20000) — from whatever it is told, and then compacts 13000 tokens below that. So the
# session ends up compacting at (window - headroom - 20000 - 13000) and hard-stopping
# at (window - headroom - 20000 - 3000), both safely under the real input cap of
# (window - max_tokens). Subtracting the output reservation here as well — which is the
# obvious thing to do, and what this wrapper used to do — double-counts it and throws
# away 20000 tokens of context for nothing. On a 111200-token window that is the
# difference between compacting at 58200 and at 37240.
CONTEXT_FOR_CLI=$(( LOGOS_CONTEXT_TOKENS - LOGOS_CONTEXT_HEADROOM ))
COMPACT_AT=$(( CONTEXT_FOR_CLI - LOGOS_MAX_OUTPUT_TOKENS - 13000 ))
HARD_STOP_AT=$(( CONTEXT_FOR_CLI - LOGOS_MAX_OUTPUT_TOKENS - 3000 ))

# ── Is there room for a session at all? ─────────────────────────────────────────
# Claude Code's opening prompt — its system prompt plus the schemas of every tool
# it carries — is around 13000 tokens before the user has typed anything, and none
# of it is compactable: it is what makes the agent an agent. Since the output
# reservation is charged against the same window, a narrow window can leave less
# input room than that, and then the FIRST request of the session comes back as
#
#   This model's maximum context length is 32768 tokens. However, you requested
#   20000 output tokens and your prompt contains at least 12769 input tokens
#
# with no way for the session to recover: there is nothing to compact yet. The
# check that used to sit here only caught the arithmetic going negative
# (headroom + reservation >= window), which a 32768-token window passes
# comfortably while being unusable — 32768 - 20000 = 12768 tokens of input, one
# token short of the opening prompt. So the floor is that prompt.
#
# It is recorded rather than acted on immediately, because --check exists to
# diagnose exactly this: it prints the arithmetic and the way out, and only a real
# start refuses to run.
CLAUDE_CODE_BASE_PROMPT_TOKENS=13000
CONTEXT_TOO_SMALL=0
# What the reservation would have to be for the opening prompt to fit — measured
# against the auto-compact point (13000) rather than the hard stop (3000), because
# a value that only clears the hard stop leaves auto-compaction firing on every
# turn, which is a working session in name only. Offered only when what is left is
# still a usable reply length; below that the window itself is the problem and
# pointing at the knob would be a dead end.
AFFORDABLE_OUTPUT_TOKENS=$(( LOGOS_CONTEXT_TOKENS - LOGOS_CONTEXT_HEADROOM - 13000 - CLAUDE_CODE_BASE_PROMPT_TOKENS ))
if (( HARD_STOP_AT < CLAUDE_CODE_BASE_PROMPT_TOKENS )); then
  CONTEXT_TOO_SMALL=1
fi

# Group digits in threes. printf "%'d" would do this, but only under a locale
# that defines a thousands separator — under LANG=C, which is what a login shell
# often ends up with, it silently prints 111200 and the number becomes unreadable.
# So the grouping is done here rather than left to the environment.
thousands() {
  local n="$1" out="" sign=""
  [[ "$n" == -* ]] && { sign="-"; n="${n#-}"; }
  [[ "$n" =~ ^[0-9]+$ ]] || { printf '%s' "$1"; return; }
  while (( ${#n} > 3 )); do
    out=",${n: -3}$out"
    n="${n:0:${#n}-3}"
  done
  printf '%s%s%s' "$sign" "$n" "$out"
}

context_report() {
  printf 'model    : %s\n' "$LOGOS_MODEL"
  printf 'logos    : %s\n' "$LOGOS_URL"
  if [[ "$CONTEXT_ORIGIN" == "estimate" ]]; then
    printf 'context  : %s tokens (an estimate — Logos reports no size for this model)\n' \
      "$(thousands "$LOGOS_CONTEXT_TOKENS")"
  elif [[ "$CONTEXT_ORIGIN" == "cold" ]]; then
    printf 'context  : %s tokens, the maximum this model is served with\n' \
      "$(thousands "$LOGOS_CONTEXT_TOKENS")"
    printf '           (no lane is up yet, so Logos reports no current size. The first request\n'
    printf '            brings one up, and how wide it comes up is decided then from whatever\n'
    printf '            capacity is free — it can land well below this number, in which case\n'
    printf '            that request is turned down and the next start sizes itself correctly)\n'
  else
    printf 'context  : %s tokens, using "%s" of what Logos offers\n' \
      "$(thousands "$LOGOS_CONTEXT_TOKENS")" "$CONTEXT_ORIGIN"
    printf '           (guaranteed %s / available now %s / model max %s)\n' \
      "$(thousands "$LOGOS_CONTEXT_GUARANTEED")" "$(thousands "$LOGOS_CONTEXT_AVAILABLE")" \
      "$(thousands "$LOGOS_CONTEXT_MAX")"
  fi
  printf 'session  : compacts itself at ~%s tokens, stops accepting at ~%s\n' \
    "$(thousands "$COMPACT_AT")" "$(thousands "$HARD_STOP_AT")"
  printf '           (%s given to Claude Code, %s kept as a margin, %s reserved for replies)\n' \
    "$(thousands "$CONTEXT_FOR_CLI")" "$(thousands "$LOGOS_CONTEXT_HEADROOM")" \
    "$(thousands "$LOGOS_MAX_OUTPUT_TOKENS")"
  context_warnings
}

context_warnings() {
  if [[ -n "$KNOWN_MODEL_IDS" ]]; then
    printf 'warning  : %s is not served here. Known models: %s\n' \
      "$LOGOS_MODEL" "$KNOWN_MODEL_IDS"
  fi
  if (( CONTEXT_TOO_SMALL )); then
    printf 'BLOCKED  : this window cannot host a Claude Code session.\n'
    printf '           %s tokens of input are left after the %s reserved for replies and\n' \
      "$(thousands "$HARD_STOP_AT")" "$(thousands "$LOGOS_MAX_OUTPUT_TOKENS")"
    printf '           the %s of headroom, and Claude Code needs about %s of that for its own\n' \
      "$(thousands "$LOGOS_CONTEXT_HEADROOM")" "$(thousands "$CLAUDE_CODE_BASE_PROMPT_TOKENS")"
    printf '           system prompt and tool definitions — so the first request is rejected.\n'
    if (( AFFORDABLE_OUTPUT_TOKENS >= 4096 )); then
      printf '           Reserving less fits, at the cost of reply length:\n'
      printf '             LOGOS_MAX_OUTPUT_TOKENS=%s claude-logos\n' "$AFFORDABLE_OUTPUT_TOKENS"
    fi
    printf '           Otherwise pick a model Logos serves with a wider window (at least %s);\n' \
      "$(thousands "$(( CLAUDE_CODE_BASE_PROMPT_TOKENS + 20000 + 3000 + 1024 ))")"
    printf '           the AI Tools page shows what each one gets.\n'
  elif (( COMPACT_AT < CLAUDE_CODE_BASE_PROMPT_TOKENS )); then
    printf 'warning  : this window is workable but tight — auto-compaction starts almost\n'
    printf '           immediately, because %s tokens are left before it fires and the system\n' \
      "$(thousands "$COMPACT_AT")"
    printf '           prompt and tools already take about %s.\n' \
      "$(thousands "$CLAUDE_CODE_BASE_PROMPT_TOKENS")"
  fi
  case "$LOGOS_MODEL" in
    claude-*|*"[1m]"*)
      printf 'warning  : Claude Code resolves this id to one of its own models and ignores\n'
      printf '           CLAUDE_CODE_MAX_CONTEXT_TOKENS for it, so the window above will not\n'
      printf '           be enforced. Pick a model whose id does not start with "claude-" or\n'
      printf '           contain "[1m]", or set DISABLE_COMPACT=1 to force the window through\n'
      printf '           (which turns auto-compaction off).\n' ;;
  esac
}

# ── Claude Code → Logos wiring ──────────────────────────────────────────────────
# All of this is exported into THIS process only. Nothing is written to a shell
# profile, to ~/.claude/settings.json or anywhere else, which is what keeps a plain
# `claude` on your Anthropic subscription.
#
# ANTHROPIC_AUTH_TOKEN sends the key as "Authorization: Bearer", which is what the
# Logos orchestrator reads. ANTHROPIC_API_KEY would use x-api-key instead, so it is
# cleared to avoid an auth-source conflict with any globally exported value.
export ANTHROPIC_BASE_URL="$LOGOS_URL"
export ANTHROPIC_AUTH_TOKEN="$LOGOS_KEY"
unset ANTHROPIC_API_KEY

# Point every model slot at the same Logos model: the primary one, the small/fast slot
# used for background tasks, and the aliases behind /model.
export ANTHROPIC_MODEL="$LOGOS_MODEL"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$LOGOS_MODEL"
export ANTHROPIC_DEFAULT_SONNET_MODEL="$LOGOS_MODEL"
export ANTHROPIC_DEFAULT_OPUS_MODEL="$LOGOS_MODEL"
export ANTHROPIC_DEFAULT_FABLE_MODEL="$LOGOS_MODEL"
export ANTHROPIC_SMALL_FAST_MODEL="$LOGOS_MODEL"   # pre-2.x name, harmless if ignored

export CLAUDE_CODE_MAX_CONTEXT_TOKENS="$CONTEXT_FOR_CLI"
export CLAUDE_CODE_MAX_OUTPUT_TOKENS="$LOGOS_MAX_OUTPUT_TOKENS"
# Keep telemetry, model discovery and other non-inference calls off api.anthropic.com,
# so the only traffic leaving this machine goes to Logos.
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# ── --check ─────────────────────────────────────────────────────────────────────
# Everything the startup line prints, plus which key and effort are in play. It
# deliberately makes no inference request: reading the model list already proves
# the URL, the key and that Logos serves this model, and a real prompt would cost
# a GPU load just to say so.
if [[ "${1:-}" == "--check" ]]; then
  context_report
  printf 'key      : %s (%s chars)\n' "$LOGOS_KEY_FILE" "${#LOGOS_KEY}"
  printf 'effort   : %s\n' "${LOGOS_EFFORT:-<not set by this wrapper>}"
  report_new_models "$(model_ids_probe)"
  report_new_revision
  refresh_latest_revision
  exit 0
fi

# ── Launch ──────────────────────────────────────────────────────────────────────
# A window too narrow for the opening prompt is refused here rather than handed to
# Claude Code, whose first request would come back as a 400 from the worker that
# reads like a bug in Logos. The report says what is left, what it costs and how
# to get around it, so this is not a dead end — and --check above still prints all
# of it without refusing anything.
if (( CONTEXT_TOO_SMALL )); then
  context_report >&2
  die "refusing to start: see BLOCKED above"
fi

command -v claude >/dev/null 2>&1 || die "claude is not on your PATH — install Claude Code first"

# Ask Logos to get the model ready before handing over. Backgrounded and
# best-effort: the session must not wait on it, and a warm-up that fails changes
# nothing except that the first request pays for the load itself.
trigger_warmup &

# Say how much room this session got. It changes between runs without anything the
# user having changed, so printing it is the difference between "Claude Code
# compacted early again" and "there was less room today".
context_report >&2
report_new_models "$(model_ids_probe)" >&2
report_new_revision >&2
refresh_latest_revision
printf '\n' >&2

settings_args=()
if [[ -n "$LOGOS_SETTINGS" && -r "$LOGOS_SETTINGS" ]]; then
  settings_args=(--settings "$LOGOS_SETTINGS")
fi

# Skip our default when an --effort was passed on the command line, so it stays
# overridable per invocation instead of being silently doubled up.
effort_args=()
if [[ -n "$LOGOS_EFFORT" ]]; then
  effort_args=(--effort "$LOGOS_EFFORT")
  for arg in "$@"; do
    [[ "$arg" == "--effort" || "$arg" == --effort=* ]] && { effort_args=(); break; }
  done
fi

exec claude "${settings_args[@]}" "${effort_args[@]}" "$@"
