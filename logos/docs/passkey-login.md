# Passkey login

Logos supports **in-page passkey (WebAuthn) login** — no redirect to a hosted
login page. The "Sign in with a passkey" button on the login screen runs the
WebAuthn ceremony directly in the app and signs the user in.

## How it works

Login is handled by `loginWithPasskey()` in
`logos-ui/src/app/core/auth/passkey.ts` and surfaced on the login page
(`logos-ui/src/app/core/auth/pages/login/login.ts`). The flow:

1. `GET {issuer}/passkey/{clientId}/challenge` — fetch a WebAuthn challenge.
2. `navigator.credentials.get(...)` — the browser prompts for a discoverable
   (usernameless) passkey and signs the challenge.
3. `POST {issuer}/passkey/{clientId}/authenticate` — the assertion is verified by
   the Keycloak passkey provider, which establishes a Keycloak SSO session.
4. **Silent token retrieval** — because Logos uses authorization-code + PKCE
   (not keycloak-js), a hidden `prompt=none` iframe pointed at
   `silent-check-sso.html` obtains an authorization code against the fresh
   session, which is exchanged for tokens. No login page is shown.

Passkeys for this login are registered against the Keycloak passkey provider
itself (`challenge` → `navigator.credentials.create(...)` → `POST .../save`) —
outside this app, so there is no in-UI registration flow for them here.

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

## Managing passkeys

Beyond the in-page login above, the webservice also runs its own passkey store
that users can manage — list, add multiple, delete — from the **Passkeys** page
(`/passkeys`) in the Logos UI. The page is reachable by URL but deliberately
not linked from the navigation while the sign-in wiring below is still a
follow-up, so the menu does not advertise a capability that is not usable
yet. Passkey storage and verification live in the webservice, which acts as a
WebAuthn relying party for registration:

- `GET /me/passkeys` — list the caller's passkeys (label, credential id,
  creation date; the public key is never exposed).
- `POST /me/passkeys/options` — server-issued WebAuthn registration options:
  a single-use 5-minute challenge bound to the user (at most 5 outstanding
  per user; issuing beyond the cap evicts the oldest), the relying party
  (id from `logos.auth.passkey.rp-id`, falling back to the request host; name
  from `logos.auth.passkey.rp-name`, default "Logos"), the user entity,
  `residentKey` + `userVerification` required, and the existing credentials
  as `excludeCredentials` (so adding is always a *new* passkey).
- `POST /me/passkeys` — submit the ceremony result (`credentialId`,
  `clientDataJSON`, `attestationObject`, the issued `challenge`, a label). The
  webservice verifies the registration per WebAuthn Level 2 §7.1: challenge
  match (and that it was issued to the caller), `clientDataJSON.origin` equal
  to the request `Origin`, `rpIdHash`, UP/UV flags, credential id match, a
  supported COSE key (ES256 or RS256) and the attestation statement
  (`none`, `packed` incl. self-attestation and x5c, `fido-u2f`) — `packed`
  requires `attStmt.alg` (WebAuthn L2 §8.2) and its ES256 signature is
  verified as IEEE P1363, while `fido-u2f` keeps the DER encoding. A
  rejected submission does not consume the challenge, and each account is
  limited to 10 passkeys (409 beyond the cap). Duplicate credentials are
  rejected with 409.
- `DELETE /me/passkeys/{id}` — delete one of the caller's passkeys (404 if
  unknown, 403 if it belongs to someone else).

Passkeys are stored in the `user_passkeys` table (one row per credential,
deleted with the user).

**Division of labour with the Keycloak provider:** the in-page *login* above
still goes through the Keycloak custom passkey provider, which is external to
this repo. Passkeys registered via the Logos UI are stored and verified by the
webservice instead; wiring those credentials into the *login* ceremony
(requirement for signing in with a webservice-registered passkey) needs the
Keycloak-side provider to be able to verify assertions against
webservice-held public keys — a follow-up.

## Notes / status

- WebAuthn needs a secure context. `localhost` counts as secure for dev; all
  other hosts need HTTPS (prod is behind Traefik TLS).
- The silent `prompt=none` iframe depends on the Keycloak session cookie being
  readable from the iframe; verify against the real Keycloak (third-party-cookie
  behaviour varies by browser).
