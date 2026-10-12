#!/bin/sh
# Compute standing-key injection values from mint/fallback, then hand off to
# the stock nginx image entrypoint (envsubst over /etc/nginx/templates).
set -eu
# shellcheck source=auth_injection_env.sh
. /auth_injection_env.sh
set_agent_auth_injection_env
exec /docker-entrypoint.sh "$@"
