# Passkey login

Logos supports **in-page passkey (WebAuthn) login** — no redirect to a hosted
login page. The "Sign in with a passkey" button on the login screen runs the
WebAuthn ceremony directly in the app and signs the user in.

## How it works

Login is handled by `logos-ui/lib/auth/passkey.ts` and surfaced in
`components/main.tsx`. The flow:

1. `GET {issuer}/passkey/{clientId}/challenge` — fetch a WebAuthn challenge.
2. `navigator.credentials.get(...)` — the browser prompts for a discoverable
   (usernameless) passkey and signs the challenge.
3. `POST {issuer}/passkey/{clientId}/authenticate` — the assertion is verified by
   the Keycloak passkey provider, which establishes a Keycloak SSO session.
4. **Silent token retrieval** — because Logos uses authorization-code + PKCE
   (not keycloak-js), a hidden `prompt=none` iframe pointed at
   `silent-check-sso.html` obtains an authorization code against the fresh
   session, which is exchanged for tokens. No login page is shown.

Registration (`registerPasskey`) mirrors this with `challenge` →
`navigator.credentials.create(...)` → `POST .../save`.

## Keycloak prerequisites

These live on the Keycloak side, not in this repo:

- The **custom passkey provider** must be enabled for the `logos` client, exposing
  `{issuer}/passkey/{logos}/{health|challenge|authenticate|save}`.
- The `logos` client must allow the silent flow: the UI origin in **Web Origins**
  and `{origin}/silent-check-sso.html` in **Valid Redirect URIs**.
- The WebAuthn **passwordless policy** (resident key + user verification) must be
  configured, and the passkey **rpId** must match what the credential was
  registered with. On the shared TUM Keycloak passkeys are scoped to the parent
  domain, so the rpId must be `aet.cit.tum.de` (NOT `logos.aet.cit.tum.de`) — a
  page on `logos.aet.cit.tum.de` is allowed to use the parent as rpId, and the
  credential is then shared across `*.aet.cit.tum.de` apps.

  The rpId is configured server-side via `KEYCLOAK_PASSKEY_RP_ID` (served to the
  UI through `/info`); the compose default is `aet.cit.tum.de` for prod. When
  blank (dev), `passkey.ts` falls back to the current hostname (e.g. `localhost`).

## Notes / status

- WebAuthn needs a secure context. `localhost` counts as secure for dev; all
  other hosts need HTTPS (prod is behind Traefik TLS).
- The silent `prompt=none` iframe depends on the Keycloak session cookie being
  readable from the iframe; verify against the real Keycloak (third-party-cookie
  behaviour varies by browser).
