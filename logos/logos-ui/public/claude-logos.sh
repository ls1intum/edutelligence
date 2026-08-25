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
#   claude-logos --logos-check        check the connection and the model, then exit
#   claude-logos --logos-context      show how much context this session would get
#   claude-logos --logos-install      install to ~/.local/bin (reads config from stdin)
#   claude-logos --logos-uninstall    remove the wrapper, its config and its key
#   claude-logos --logos-help         this text
#
# NOTHING OUTSIDE THIS WRAPPER IS TOUCHED. The Logos credential, base URL and model are
# exported into the child process only, and the extra Claude Code settings live in this
# wrapper's own directory and are handed over with --settings. Your shell profile,
# ~/.claude/settings.json and your claude.ai login are left exactly as they are, so plain
# `claude` keeps using your Anthropic subscription with no reconfiguration.
#
# This file is served by the Logos UI at <logos-url>/claude-logos.sh and is what the
# "AI Tools" page installs.
#
set -euo pipefail

CONFIG_DIR="${LOGOS_CONFIG_DIR:-$HOME/.config/claude-logos}"
CONFIG_FILE="$CONFIG_DIR/config"
KEY_FILE_DEFAULT="$CONFIG_DIR/key"
SETTINGS_FILE_DEFAULT="$CONFIG_DIR/settings.json"
INSTALL_PATH="${LOGOS_INSTALL_PATH:-$HOME/.local/bin/claude-logos}"

# ── Settings, lowest precedence first ───────────────────────────────────────────
# The config file is written by --logos-install (i.e. by the AI Tools page) and holds
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
# arithmetic printed by --logos-context.
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
  sed -n '3,26p' "$0" | sed 's/^# \{0,1\}//'
}

# ── --logos-install ─────────────────────────────────────────────────────────────
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
  [[ -n "$key" ]] || die "--logos-install needs a LOGOS_KEY=… line on stdin"
  [[ -n "$url" ]] || die "--logos-install needs a LOGOS_URL=… line on stdin"

  mkdir -p "$(dirname "$INSTALL_PATH")" "$CONFIG_DIR"
  chmod 700 "$CONFIG_DIR"

  # Copy this script rather than symlink it: the download it came from is a temp file.
  if [[ "$(cd "$(dirname "$0")" && pwd)/$(basename "$0")" != "$INSTALL_PATH" ]]; then
    cat "$0" > "$INSTALL_PATH"
  fi
  chmod 755 "$INSTALL_PATH"

  ( umask 177; printf '%s\n' "${key//[$'\r\n']/}" > "$LOGOS_KEY_FILE" )

  { printf '# Written by claude-logos --logos-install. Environment variables win over this file.\n'
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

# ── --logos-uninstall ───────────────────────────────────────────────────────────
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
        note "not a terminal — re-run with --logos-uninstall --yes to remove them too"
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

  for path in "$LOGOS_KEY_FILE" "$SETTINGS_FILE_DEFAULT" "$CONFIG_FILE"; do
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
# Only the --logos-* verbs are ours; everything else goes to claude untouched, which
# is what makes `claude-logos <anything>` behave like `claude <anything>`.
case "${1:-}" in
  --logos-help|--logos-usage) usage; exit 0 ;;
  --logos-install) shift; logos_install; exit 0 ;;
  --logos-uninstall)
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
# uses; the other two are Logos extensions. Older gateways send only the first,
# so every step falls back to the one below it.
guaranteed = window("max_model_len")
available = window("max_model_len_best") or guaranteed
maximum = window("max_context_length") or available
chosen = {
    "guaranteed": guaranteed,
    "available": available,
    "max": maximum,
}.get(source, available) or guaranteed
print(f"window\t{chosen}\t{guaranteed}\t{available}\t{maximum}")
' "$LOGOS_MODEL" "$LOGOS_CONTEXT_SOURCE" || true
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

if (( LOGOS_CONTEXT_HEADROOM + LOGOS_MAX_OUTPUT_TOKENS >= LOGOS_CONTEXT_TOKENS )); then
  die "context window $LOGOS_CONTEXT_TOKENS is too small for the \
$LOGOS_MAX_OUTPUT_TOKENS-token output reservation plus $LOGOS_CONTEXT_HEADROOM headroom"
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

thousands() { printf "%'d" "$1" 2>/dev/null || printf '%d' "$1"; }

context_report() {
  printf 'model    : %s\n' "$LOGOS_MODEL"
  printf 'logos    : %s\n' "$LOGOS_URL"
  if [[ "$CONTEXT_ORIGIN" == "estimate" ]]; then
    printf 'context  : %s tokens (an estimate — Logos reports no size for this model)\n' \
      "$(thousands "$LOGOS_CONTEXT_TOKENS")"
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

# ── --logos-context ─────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--logos-context" ]]; then
  context_report
  exit 0
fi

# ── --logos-check ───────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--logos-check" ]]; then
  context_report
  printf 'key      : %s (%s chars)\n' "$LOGOS_KEY_FILE" "${#LOGOS_KEY}"
  printf 'effort   : %s\n' "${LOGOS_EFFORT:-<not set by this wrapper>}"
  printf 'probe    : '
  probe_body="$(mktemp)"
  code="$(curl -s -o "$probe_body" -w '%{http_code}' -m 180 \
    "$LOGOS_URL/v1/messages" \
    -H "Authorization: Bearer $LOGOS_KEY" \
    -H 'anthropic-version: 2023-06-01' \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$LOGOS_MODEL\",\"max_tokens\":16,\"messages\":[{\"role\":\"user\",\"content\":\"Reply with: OK\"}]}")"
  body="$(head -c 400 "$probe_body")"; rm -f "$probe_body"
  if [[ "$code" == "200" ]]; then
    printf 'HTTP 200 — Logos reachable, key and model accepted\n'
    exit 0
  fi
  printf 'HTTP %s\n%s\n' "$code" "$body"
  case "$code" in
    401|403) note "key rejected or not permitted for this model — check $LOGOS_KEY_FILE" ;;
    404)     note "Logos does not serve '$LOGOS_MODEL', or LOGOS_URL is wrong" ;;
    000)     note "no response — check the VPN/network, or the model is starting up (>180s)" ;;
  esac
  exit 1
fi

# ── Launch ──────────────────────────────────────────────────────────────────────
command -v claude >/dev/null 2>&1 || die "claude is not on your PATH — install Claude Code first"

# Say which window this session got. It changes between runs without anything the user
# did changing, so printing it is the difference between "Claude Code compacted early
# again" and "this lane is running narrow today".
context_report >&2
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
