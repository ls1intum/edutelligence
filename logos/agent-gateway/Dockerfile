# The model gateway the agent's session containers talk to.
#
# The configuration is baked in rather than bind-mounted from the host. A
# deployment of this stack copies exactly one file to its VM — the compose
# file — so a mount of `./agent-gateway/nginx.conf` resolved to a path that
# does not exist there, Docker created an empty *directory* in its place,
# and nginx came up with its stock configuration: no /v1 proxying, no
# credential injection, no /healthz. The container then failed its health
# check forever and the runner's `service_healthy` dependency never
# released. Shipping the file inside the image removes the whole class of
# that failure.
#
# It stays a *template*: the image's entrypoint sets injection values from
# mint/fallback, then the stock nginx entrypoint runs envsubst over
# /etc/nginx/templates — so keys and policy enter the running configuration,
# not an image layer.
FROM nginx:1.31-alpine

COPY logos/agent-gateway/auth_injection_env.sh /auth_injection_env.sh
COPY logos/agent-gateway/entrypoint.sh /entrypoint.sh
COPY logos/agent-gateway/00-agent-auth-map.conf.template /etc/nginx/templates/00-agent-auth-map.conf.template
COPY logos/agent-gateway/nginx.conf /etc/nginx/templates/default.conf.template
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
