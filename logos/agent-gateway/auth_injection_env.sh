# Shared by the gateway entrypoint and the template-render test.
# Exports AGENT_AUTH_EMPTY / AGENT_AUTH_PLACEHOLDER for envsubst.
#
# Standing-key injection is allowed when minting is off, or when minting is
# on and fallback is on. When minting is required without fallback, empty
# and placeholder Authorization values must stay empty so nginx can reject.
set_agent_auth_injection_env() {
    mint=$(printf '%s' "${LOGOS_AGENT_SESSION_API_KEY_MINT:-false}" | tr '[:upper:]' '[:lower:]')
    fallback=$(printf '%s' "${LOGOS_AGENT_SESSION_API_KEY_FALLBACK:-false}" | tr '[:upper:]' '[:lower:]')

    inject=true
    case "$mint" in
        1|true|yes|on)
            case "$fallback" in
                1|true|yes|on) ;;
                *) inject=false ;;
            esac
            ;;
    esac

    if [ "$inject" = true ]; then
        export AGENT_AUTH_EMPTY="Bearer ${LOGOS_AGENT_API_KEY}"
        export AGENT_AUTH_PLACEHOLDER="Bearer ${LOGOS_AGENT_API_KEY}"
    else
        export AGENT_AUTH_EMPTY=
        export AGENT_AUTH_PLACEHOLDER=
    fi
}
