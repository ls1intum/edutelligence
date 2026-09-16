#!/bin/sh
# The rate gateway's container entrypoint. Runs ahead of the stock
# /docker-entrypoint.sh, which performs the envsubst pass over
# /etc/nginx/templates and starts nginx.
set -eu

# A character allowlist is NOT validation: "999.999.999.999" and
# "1.2.3.4/33" pass any character check, but nginx then rejects the
# generated configuration and the gateway would crashloop — and with it
# the whole stack, since every request funnels through it. So each entry
# is parsed as a full IPv4 address (four dotted octets, no leading zeros)
# with an optional /0-32 prefix before it is written anywhere.

# Octet: 0, 1-9, 10-99, or 100-255. Leading zeros are rejected because
# nginx rejects them in address directives.
is_octet() {
    case "$1" in
        0) return 0 ;;
        [1-9]) return 0 ;;
        [1-9][0-9]) return 0 ;;
        [1-9][0-9][0-9]) [ "$1" -le 255 ] && return 0 || return 1 ;;
        *) return 1 ;;
    esac
}

# Four dotted octets, nothing else.
is_ipv4() {
    a=$1
    o1=${a%%.*}; [ "$o1" = "$a" ] && return 1; a=${a#*.}
    o2=${a%%.*}; [ "$o2" = "$a" ] && return 1; a=${a#*.}
    o3=${a%%.*}; [ "$o3" = "$a" ] && return 1; a=${a#*.}
    case "$a" in *.*) return 1 ;; esac
    is_octet "$o1" && is_octet "$o2" && is_octet "$o3" && is_octet "$a"
}

# A plain IPv4 address or IPv4/CIDR (prefix 0-32).
is_ip_entry() {
    case "$1" in
        */*)
            prefix=${1##*/}
            addr=${1%/*}
            case "$prefix" in '' | *[!0-9]*) return 1 ;; esac
            [ "$prefix" -le 32 ] || return 1
            ;;
        *)
            addr=$1
            ;;
    esac
    is_ipv4 "$addr"
}

# Render the whitelist geo block from LOGOS_RATE_LIMIT_WHITELISTED_IPS
# (space-separated IPv4 addresses and CIDRs, from the deployment's .env).
# It is written to a file of its own instead of living in the template
# because a geo block cannot be left empty by envsubst — with no entries
# the line would degrade to a bare "1;" and fail nginx -t. Invalid
# entries are rejected with a message rather than taken down: a typo in
# .env must degrade to "no whitelist", not to a crashloop.
WHITELIST_ENTRIES=""
for ip in ${LOGOS_RATE_LIMIT_WHITELISTED_IPS:-}; do
    if is_ip_entry "$ip"; then
        WHITELIST_ENTRIES="${WHITELIST_ENTRIES}    ${ip} 1;
"
    else
        echo "rate-gateway: ignoring invalid whitelist entry: $ip (expected IPv4 or IPv4/CIDR)" >&2
    fi
done
{
    echo 'geo $rl_whitelisted {'
    echo '    default 0;'
    printf '%s' "$WHITELIST_ENTRIES"
    echo '}'
} > /etc/nginx/rate-gateway/whitelist.conf

# Same treatment for the trusted-proxy ranges: set_real_ip_from takes
# exactly one parameter per directive, so one line per range, and each
# range is parsed with the same validator (an invalid one would fail
# nginx -t the same way).
{
    for cidr in ${LOGOS_GATEWAY_TRUSTED_PROXY_CIDRS:-}; do
        if is_ip_entry "$cidr"; then
            echo "set_real_ip_from ${cidr};"
        else
            echo "rate-gateway: ignoring invalid trusted-proxy CIDR: $cidr (expected IPv4 or IPv4/CIDR)" >&2
        fi
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
