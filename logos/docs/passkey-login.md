# Passkey login

Logos supports **in-page passkey (WebAuthn) login**. The user does not go to
a hosted login page. The "Sign in with a passkey" button on the login screen
runs the WebAuthn ceremony in the app and signs the user in.

## How it works

The implementation is in `logos-ui/src/app/core/auth/` (Angular). These files
do the work:

- `passkey.ts` runs the WebAuthn ceremony and the silent token exchange.
- `keycloak.ts` manages the keycloak-js singleton. The singleton starts with
  check-sso and PKCE.
- `services/auth.service.ts` completes the login.

The flow has these steps:

1. `GET {issuer}/passkey/{clientId}/challenge` gets a WebAuthn challenge.
2. `navigator.credentials.get(...)` asks the browser for a discoverable
   (usernameless) passkey. The browser signs the challenge
   (`userVerification: "required"`).
3. `POST {issuer}/passkey/{clientId}/authenticate` sends the assertion. The
   Keycloak passkey provider verifies it and creates a Keycloak SSO session.
4. **Silent token retrieval**: a hidden `prompt=none` iframe completes
   authorization-code + PKCE against the new session
   (`silent-check-sso.html`). The app gets the tokens and the user sees no
   login page.
5. **Install into keycloak-js**: `AuthService.completeLogin()` puts the tokens
   into the keycloak-js instance of the app. The auth interceptor (`kc.token`)
   and its `updateToken()` refresh continue to work with no redirect.

Registration (`registerPasskey` in `passkey.ts`) uses the same flow. The steps
are `challenge`, then `navigator.credentials.create(...)`, then
`POST .../save`.

## Keycloak prerequisites

These items are on the Keycloak side. They are not in this repository.

- Enable the **custom passkey provider** for the `logos` client. The provider
  exposes `{issuer}/passkey/{logos}/{health|challenge|authenticate|save}`.
- Configure the `logos` client for the silent flow. Add the UI origin to
  **Web Origins**. Add `{origin}/silent-check-sso.html` to **Valid Redirect
  URIs**.
- Configure the WebAuthn **passwordless policy** (resident key and user
  verification). The passkey **rpId** must be the same as the rpId of the
  registered credential.
- On the shared TUM Keycloak, passkeys are scoped to the parent domain. The
  rpId must be `aet.cit.tum.de` (NOT `logos.aet.cit.tum.de`). A page on
  `logos.aet.cit.tum.de` can use the parent as rpId. Then all
  `*.aet.cit.tum.de` apps share the credential.

The server sets the rpId with `KEYCLOAK_PASSKEY_RP_ID`. The server sends the
value to the UI through `/api/info`. The default in the production compose
file is `aet.cit.tum.de`. If the value is blank (dev), then `passkey.ts` uses
the current hostname (for example `localhost`).

## Notes / status

- WebAuthn needs a secure context. `localhost` is a secure context for dev.
  All other hosts need HTTPS (prod is behind Traefik TLS).
- The silent `prompt=none` iframe needs to read the Keycloak session cookie.
  Verify this against the real Keycloak, because the handling of third-party
  cookies is different in different browsers.
