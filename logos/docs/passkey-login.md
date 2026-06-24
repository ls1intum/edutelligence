# Passkey login

Logos supports **passwordless passkey (WebAuthn) login** in addition to the
existing username/password sign-in. Like the rest of Logos auth, login is
handled entirely by the **Keycloak-hosted login page** — the UI redirects to
Keycloak via OIDC (`expo-auth-session`, see `logos-ui/components/main.tsx`), so
there is no in-app WebAuthn code. Passkeys are enabled purely through Keycloak
realm configuration (`logos/keycloak/tum-realm.json`).

## How it works

The realm binds a custom `browser-passkey` authentication flow:

```
browser-passkey
├── Cookie                                  (ALTERNATIVE)  ← existing SSO session
├── Identity Provider Redirector            (ALTERNATIVE)
└── browser-passkey-forms                   (ALTERNATIVE)
    ├── Username Form                        (REQUIRED)    ← enter username/email
    └── browser-passkey-passwordless-or-password (REQUIRED)
        ├── WebAuthn Passwordless Authenticator (ALTERNATIVE) ← passkey
        └── browser-passkey-password         (ALTERNATIVE)
            └── Password Form                (REQUIRED)    ← fallback
```

After entering their username, a user with a registered passkey is prompted for
it; everyone else falls back to the password form. Existing password logins keep
working unchanged.

The passwordless WebAuthn policy is configured with
`requireResidentKey: "Yes"` and `userVerification: "required"`, which makes the
registered credentials true **discoverable passkeys** (synced via the platform
authenticator / password manager). `signatureAlgorithms` allows `ES256` and
`RS256`.

`webAuthnPolicyPasswordlessRpId` is intentionally left **empty** so Keycloak
derives the WebAuthn Relying Party ID from the request host. This works for both
`localhost` in dev and the production Keycloak hostname
(`keycloak.aet.cit.tum.de`) without per-environment overrides. A passkey is
bound to the RP ID (the Keycloak host), so passkeys registered against dev do
not work against prod and vice versa — this is expected WebAuthn behaviour.

## Registering a passkey

A user registers a passkey from the Keycloak **account console** → *Account
security* → *Signing in* → *Passkey* → *Add*. This is driven by the
`webauthn-register-passwordless` required action, which Keycloak provisions and
enables by default.

To force enrollment you can instead make it a default action (admin console →
*Authentication* → *Required actions* → enable *Set as default action* for
*Webauthn Register Passwordless*), which prompts every user to add a passkey on
their next login. Logos ships it as opt-in (not a default action).

## Testing locally

1. Bring up the dev stack (includes Keycloak):
   ```
   cd logos && docker compose -f docker-compose.dev.yaml up --build
   ```
2. Open the UI (`http://localhost:18081`) and click **Sign in**.
3. On the Keycloak page, enter a seed user (e.g. `tobias.wasner` /
   `password`) and log in once with the password.
4. Open the account console at
   `http://localhost:8085/realms/tum/account` → *Signing in* → add a passkey
   (Chrome/Safari offer a virtual or platform authenticator).
5. Log out and sign in again — after entering the username you are now offered
   the passkey instead of the password.

> WebAuthn requires a secure context. `localhost` is treated as secure by
> browsers, so dev works over plain HTTP; any other host needs HTTPS (prod is
> behind Traefik TLS, so this is satisfied).

## Verifying after a realm change

Because Keycloak only imports the realm on first creation (`--import-realm`),
changes to `tum-realm.json` need a fresh realm. In dev, recreate the Keycloak
volume/container:

```
cd logos && docker compose -f docker-compose.dev.yaml up -d --force-recreate keycloak
```

Then confirm in the admin console (`admin` / `admin`):
- *Authentication* → *Flows* → the bound browser flow is **browser-passkey**.
- *Authentication* → *Policies* → *WebAuthn Passwordless Policy* shows the
  passkey settings above.
