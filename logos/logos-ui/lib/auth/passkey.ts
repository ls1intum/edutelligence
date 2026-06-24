// In-page passkey (WebAuthn) login for the Logos UI.
//
// Logos uses raw authorization-code + PKCE (not keycloak-js), so after the passkey
// ceremony establishes a Keycloak SSO session we silently retrieve tokens via a
// hidden `prompt=none` iframe (the classic Keycloak "check-sso" pattern).
//
// Keycloak-side prerequisite: the custom passkey provider must be enabled for the
// `logos` client. Endpoints live at
// `{issuer}/passkey/{clientId}/{health|challenge|authenticate|save}`.
// See docs/passkey-login.md.

import * as Crypto from "expo-crypto";

import { KeycloakConfig, passkeyEndpoint, StoredTokens } from "./keycloak";

const SILENT_REDIRECT_PATH = "/silent-check-sso.html";
const CEREMONY_TIMEOUT_MS = 60_000;

export function isPasskeySupported(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    typeof window.PublicKeyCredential !== "undefined" &&
    typeof navigator !== "undefined" &&
    typeof navigator.credentials !== "undefined"
  );
}

// WebAuthn rpId must be a registrable suffix of the page origin AND match what the
// passkey was registered with in Keycloak. Default to the current host; override
// via the optional argument if the shared provider scopes passkeys to a parent
// domain (e.g. aet.cit.tum.de).
export function defaultRpId(): string {
  return typeof window !== "undefined" ? window.location.hostname : "";
}

// ── base64url <-> bytes ──────────────────────────────────────────────────────

function toBase64Url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function fromBase64Url(value: string): Uint8Array {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export function isPasskeyCancellation(error: unknown): boolean {
  return (
    error instanceof DOMException &&
    (error.name === "NotAllowedError" || error.name === "AbortError")
  );
}

export function passkeyErrorMessage(error: unknown, fallback = "Passkey sign-in failed."): string {
  if (error instanceof DOMException) {
    if (isPasskeyCancellation(error)) return "Passkey sign-in was cancelled.";
    if (error.name === "InvalidStateError") return "This passkey is already registered.";
    if (error.name === "SecurityError") return "Passkeys are not allowed on this site.";
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

// Best-effort human label saved with a newly registered passkey.
export function getDeviceName(): string {
  if (typeof navigator === "undefined") return "Unknown device";
  const ua = navigator.userAgent;
  const platform = /Mac/.test(ua)
    ? "Mac"
    : /Win/.test(ua)
      ? "Windows"
      : /Linux/.test(ua)
        ? "Linux"
        : /Android/.test(ua)
          ? "Android"
          : /iPhone|iPad/.test(ua)
            ? "iOS"
            : "Unknown";
  const browser = /Firefox/.test(ua)
    ? "Firefox"
    : /Edg/.test(ua)
      ? "Edge"
      : /Chrome/.test(ua)
        ? "Chrome"
        : /Safari/.test(ua)
          ? "Safari"
          : "Browser";
  return `${platform} - ${browser}`;
}

// ── Keycloak passkey provider calls ──────────────────────────────────────────

export async function isPasskeyProviderAvailable(cfg: KeycloakConfig): Promise<boolean> {
  try {
    const res = await fetch(passkeyEndpoint(cfg, "health"), {
      method: "GET",
      credentials: "include",
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  }
}

async function requestChallenge(cfg: KeycloakConfig): Promise<string> {
  const res = await fetch(passkeyEndpoint(cfg, "challenge"), {
    method: "GET",
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Passkey challenge failed (${res.status})`);
  const data = (await res.json().catch(() => undefined)) as { challenge?: string } | undefined;
  if (!data?.challenge) throw new Error("Passkey challenge response missing 'challenge'");
  return data.challenge;
}

function jwtSubject(accessToken: string): string | undefined {
  try {
    const payload = accessToken.split(".")[1];
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return (JSON.parse(json) as { sub?: string }).sub;
  } catch {
    return undefined;
  }
}

/**
 * Authenticate with a discoverable (usernameless) passkey, then exchange the
 * resulting Keycloak SSO session for OIDC tokens via a silent iframe.
 */
export async function loginWithPasskey(
  cfg: KeycloakConfig,
  rpId: string = defaultRpId()
): Promise<StoredTokens> {
  if (!isPasskeySupported()) throw new Error("This browser does not support passkeys.");

  const challenge = await requestChallenge(cfg);
  const credential = await navigator.credentials.get({
    publicKey: {
      challenge: fromBase64Url(challenge) as BufferSource,
      rpId,
      userVerification: "required",
      timeout: CEREMONY_TIMEOUT_MS,
    },
  });

  if (!(credential instanceof PublicKeyCredential)) {
    throw new Error("No passkey credential was returned.");
  }
  const response = credential.response;
  if (!(response instanceof AuthenticatorAssertionResponse) || !response.userHandle) {
    throw new Error("Unexpected passkey authentication response.");
  }

  const authRes = await fetch(passkeyEndpoint(cfg, "authenticate"), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      credentialId: toBase64Url(credential.rawId),
      userHandle: toBase64Url(response.userHandle),
      clientDataJSON: toBase64Url(response.clientDataJSON),
      authenticatorData: toBase64Url(response.authenticatorData),
      signature: toBase64Url(response.signature),
      challenge,
    }),
  });
  if (!authRes.ok) throw new Error(`Passkey authentication rejected (${authRes.status})`);

  // The provider has now established a Keycloak SSO session (cookie). Pull tokens
  // for the `logos` client silently, without showing the hosted login page.
  return silentTokenExchange(cfg);
}

/**
 * Register a new passkey for the currently logged-in user.
 */
export async function registerPasskey(
  cfg: KeycloakConfig,
  accessToken: string,
  rpId: string = defaultRpId(),
  rpName = "Logos"
): Promise<void> {
  if (!isPasskeySupported()) throw new Error("This browser does not support passkeys.");
  const sub = jwtSubject(accessToken);
  if (!sub) throw new Error("Cannot register a passkey: access token has no subject.");

  const challenge = await requestChallenge(cfg);
  const credential = await navigator.credentials.create({
    publicKey: {
      challenge: fromBase64Url(challenge) as BufferSource,
      rp: { name: rpName, id: rpId },
      user: {
        id: new TextEncoder().encode(sub) as BufferSource,
        name: getDeviceName(),
        displayName: getDeviceName(),
      },
      pubKeyCredParams: [
        { type: "public-key", alg: -7 }, // ES256
        { type: "public-key", alg: -257 }, // RS256
      ],
      authenticatorSelection: { residentKey: "required", userVerification: "required" },
      timeout: CEREMONY_TIMEOUT_MS,
    },
  });

  if (!(credential instanceof PublicKeyCredential)) {
    throw new Error("No passkey credential was returned.");
  }
  const response = credential.response;
  if (!(response instanceof AuthenticatorAttestationResponse)) {
    throw new Error("Unexpected passkey registration response.");
  }

  const saveRes = await fetch(passkeyEndpoint(cfg, "save"), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({
      credentialId: toBase64Url(credential.rawId),
      clientDataJSON: toBase64Url(response.clientDataJSON),
      attestationObject: toBase64Url(response.attestationObject),
      challenge,
      label: getDeviceName(),
    }),
  });
  if (!saveRes.ok) throw new Error(`Passkey registration rejected (${saveRes.status})`);
}

// ── Silent token retrieval (prompt=none authorization-code + PKCE) ───────────

async function pkcePair(): Promise<{ verifier: string; challenge: string }> {
  const verifier = (Crypto.randomUUID() + Crypto.randomUUID()).replace(/-/g, "");
  const digest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    verifier,
    { encoding: Crypto.CryptoEncoding.BASE64 }
  );
  const challenge = digest.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  return { verifier, challenge };
}

async function silentTokenExchange(cfg: KeycloakConfig): Promise<StoredTokens> {
  const redirectUri = `${window.location.origin}${SILENT_REDIRECT_PATH}`;
  const { verifier, challenge } = await pkcePair();
  const state = Crypto.randomUUID();
  const nonce = Crypto.randomUUID();

  const authUrl =
    `${cfg.endpoints.authorizationEndpoint}?` +
    new URLSearchParams({
      client_id: cfg.clientId,
      redirect_uri: redirectUri,
      response_type: "code",
      scope: "openid profile email",
      prompt: "none",
      code_challenge: challenge,
      code_challenge_method: "S256",
      state,
      nonce,
    }).toString();

  const code = await codeFromSilentIframe(authUrl, redirectUri, state);

  const tokenRes = await fetch(cfg.endpoints.tokenEndpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: cfg.clientId,
      code,
      code_verifier: verifier,
      redirect_uri: redirectUri,
    }).toString(),
  });
  if (!tokenRes.ok) throw new Error(`Silent token exchange failed (${tokenRes.status})`);
  const data = await tokenRes.json();
  return {
    accessToken: data.access_token,
    refreshToken: data.refresh_token ?? null,
    expiresAt: Math.floor(Date.now() / 1000) + (data.expires_in ?? 300),
  };
}

// Loads the prompt=none auth URL in a hidden iframe; silent-check-sso.html posts
// the redirected URL (carrying ?code) back to us. Resolves with the auth code.
function codeFromSilentIframe(authUrl: string, redirectUri: string, state: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const iframe = document.createElement("iframe");
    iframe.style.display = "none";
    let settled = false;

    const cleanup = () => {
      window.removeEventListener("message", onMessage);
      clearTimeout(timer);
      iframe.remove();
    };
    const fail = (msg: string) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new Error(msg));
    };

    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      if (typeof event.data !== "string" || !event.data.startsWith(redirectUri)) return;
      const params = new URL(event.data).searchParams;
      if (params.get("state") !== state) return fail("Silent login state mismatch.");
      const err = params.get("error");
      if (err) return fail(`Silent login failed: ${err}`);
      const code = params.get("code");
      if (!code) return fail("Silent login returned no authorization code.");
      settled = true;
      cleanup();
      resolve(code);
    };

    const timer = setTimeout(() => fail("Silent login timed out."), CEREMONY_TIMEOUT_MS);
    window.addEventListener("message", onMessage);
    iframe.src = authUrl;
    document.body.appendChild(iframe);
  });
}
