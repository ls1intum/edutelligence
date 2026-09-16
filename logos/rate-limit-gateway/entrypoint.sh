#!/bin/sh
# The rate gateway's container entrypoint. Runs ahead of the stock
# /docker-entrypoint.sh, which performs the envsubst pass over
# /etc/nginx/templates and starts nginx.
set -eu

# Render the whitelist geo block from LOGOS_RATE_LIMIT_WHITELISTED_IPS
# (space-separated IPv4 addresses and CIDRs, from the deployment's .env).
# It is written to a file of its own instead of living in the template
# because a geo block cannot be left empty by envsubst — with no entries
# the line would degrade to a bare "1;" and fail nginx -t. Malformed
# entries are rejected with a message rather than taken down: a typo in
# .env must degrade to "no whitelist", not to a crashloop.
WHITELIST_ENTRIES=""
for ip in ${LOGOS_RATE_LIMIT_WHITELISTED_IPS:-}; do
    case "$ip" in
        *[!0-9a-fA-F.:/]*)
            echo "rate-gateway: ignoring malformed whitelist entry: $ip" >&2
            ;;
        *)
            WHITELIST_ENTRIES="${WHITELIST_ENTRIES}    ${ip} 1;
"
            ;;
    esac
done
{
    echo 'geo $rl_whitelisted {'
    echo '    default 0;'
    printf '%s' "$WHITELIST_ENTRIES"
    echo '}'
} > /etc/nginx/rate-gateway/whitelist.conf

# Same treatment for the trusted-proxy ranges: set_real_ip_from takes
# exactly one parameter per directive, so one line per range.
{
    for cidr in ${LOGOS_GATEWAY_TRUSTED_PROXY_CIDRS:-}; do
        case "$cidr" in
            *[!0-9a-fA-F.:/]*)
                echo "rate-gateway: ignoring malformed trusted-proxy CIDR: $cidr" >&2
                ;;
            *)
                echo "set_real_ip_from ${cidr};"
                ;;
        esac
    done
} > /etc/nginx/rate-gateway/realip.conf

# Guarantee the template's ${...} references resolve even when the image
# is run without the compose file's environment (local debugging).
export LOGOS_IP_RATE_LIMIT_AVG="${LOGOS_IP_RATE_LIMIT_AVG:-30}"
export LOGOS_IP_RATE_LIMIT_BURST="${LOGOS_IP_RATE_LIMIT_BURST:-60}"
export LOGOS_IP_CONTROL_RATE_LIMIT_AVG="${LOGOS_IP_CONTROL_RATE_LIMIT_AVG:-5}"
export LOGOS_IP_CONTROL_RATE_LIMIT_BURST="${LOGOS_IP_CONTROL_RATE_LIMIT_BURST:-20}"
export LOGOS_GATEWAY_TRUSTED_PROXY_CIDRS="${LOGOS_GATEWAY_TRUSTED_PROXY_CIDRS:-172.16.0.0/12}"
export LOGOS_GATEWAY_UPSTREAM="${LOGOS_GATEWAY_UPSTREAM:-traefik:8090}"

# The shared proxy include is a plain file (it must not sit in conf.d,
# see the Dockerfile), so its one placeholder is substituted by hand.
sed -i "s|\${LOGOS_GATEWAY_UPSTREAM}|${LOGOS_GATEWAY_UPSTREAM}|g" \
    /etc/nginx/rate-gateway/upstream.conf

exec /docker-entrypoint.sh "$@"
