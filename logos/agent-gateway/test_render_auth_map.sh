#!/bin/sh
# Template-render coverage for standing-key injection vs mint-required reject.
# Run: sh logos/agent-gateway/test_render_auth_map.sh
set -eu
cd "$(dirname "$0")"
# shellcheck source=auth_injection_env.sh
. ./auth_injection_env.sh

fail=0
assert_contains() {
    haystack=$1
    needle=$2
    label=$3
    case "$haystack" in
        *"$needle"*) ;;
        *)
            printf 'FAIL %s: expected to contain %s\nGot:\n%s\n' "$label" "$needle" "$haystack" >&2
            fail=1
            ;;
    esac
}

assert_not_contains() {
    haystack=$1
    needle=$2
    label=$3
    case "$haystack" in
        *"$needle"*)
            printf 'FAIL %s: must not contain %s\nGot:\n%s\n' "$label" "$needle" "$haystack" >&2
            fail=1
            ;;
    esac
}

render_map() {
    mint=$1
    fallback=$2
    LOGOS_AGENT_API_KEY=standing-secret \
    LOGOS_AGENT_SESSION_API_KEY_MINT=$mint \
    LOGOS_AGENT_SESSION_API_KEY_FALLBACK=$fallback \
        set_agent_auth_injection_env
    # Only substitute the injection placeholders; leave nginx $vars alone.
    envsubst '${AGENT_AUTH_EMPTY} ${AGENT_AUTH_PLACEHOLDER}' \
        < 00-agent-auth-map.conf.template
}

# Mint off: inject standing key for empty and placeholder.
out=$(render_map false false)
assert_contains "$out" '"Bearer standing-secret"' 'mint=false injects standing key'
assert_not_contains "$out" '""                                          "";' 'mint=false does not leave empty injection'

# Mint on, fallback on: injection still allowed.
out=$(render_map true true)
assert_contains "$out" '"Bearer standing-secret"' 'mint+fallback injects standing key'

# Mint on, fallback off: empty/placeholder must not inject the standing key.
out=$(render_map true false)
assert_not_contains "$out" 'standing-secret' 'mint without fallback must not inject standing key'
assert_contains "$out" '""                                          "";' 'mint without fallback maps empty header to empty'
assert_contains "$out" '"Bearer injected-by-logos-agent-gateway"    "";' 'mint without fallback maps placeholder to empty'

# default.conf must reject an empty mapped Authorization on /v1.
assert_contains "$(cat nginx.conf)" 'if ($agent_authorization = "")' 'nginx rejects empty mapped auth'
assert_contains "$(cat nginx.conf)" 'return 401;' 'nginx returns 401 when auth missing'

if [ "$fail" -ne 0 ]; then
    exit 1
fi
printf 'OK: auth map render covers allowed and rejected mint/fallback configs\n'
