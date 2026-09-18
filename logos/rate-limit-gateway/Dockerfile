# The per-IP rate-limit gateway the public entrypoints funnel through
# (see nginx.conf for the design).
#
# Like the agent gateway, the configuration is baked into the image rather
# than bind-mounted from the host: a deployment copies only the compose
# file to its VM, so a mount of ./rate-limit-gateway/... would resolve to a
# path that does not exist there, Docker would create an empty *directory*
# in its place, and nginx would start with a broken configuration.
#
# nginx.conf stays a *template*: the stock envsubst pass (nginx image)
# fills in the ${LOGOS_*} values that entrypoint.sh guarantees, and
# entrypoint.sh renders the IP whitelist from the deployment's .env before
# nginx starts.
FROM nginx:1.28-alpine

# The shared include and the rendered whitelist live OUTSIDE conf.d:
# nginx auto-includes conf.d/*.conf in the *http* context, so a file with
# location-level directives (proxy_pass) parked there would be parsed twice
# and fail with "directive is not allowed here". upstream.conf is a plain
# file, not a template: entrypoint.sh substitutes its single ${...} value.
COPY logos/rate-limit-gateway/nginx.conf /etc/nginx/templates/default.conf.template
COPY logos/rate-limit-gateway/upstream.conf /etc/nginx/rate-gateway/upstream.conf
COPY logos/rate-limit-gateway/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
