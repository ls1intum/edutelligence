// In-page passkey (WebAuthn) login for the Logos UI.
//
// The ceremony authenticates against Keycloak's custom passkey provider
// (`{issuer}/passkey/{clientId}/{health|challenge|authenticate|save}`), which
// establishes a Keycloak SSO session. The caller then runs keycloak.login() to
// obtain tokens with no visible prompt. Provider must be enabled for the client.

const CEREMONY_TIMEOUT_MS = 60_000;

export function isPasskeySupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.isSecureContext &&
    typeof window.PublicKeyCredential !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    typeof navigator.credentials !== 'undefined'
  );
}

export function defaultRpId(): string {
  return typeof window !== 'undefined' ? window.location.hostname : '';
}

export function passkeyEndpoint(issuer: string, clientId: string, path: string): string {
  const base = issuer.replace(/\/+$/, '');
  return `${base}/passkey/${encodeURIComponent(clientId)}/${path}`;
}

function toBase64Url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function fromBase64Url(value: string): Uint8Array {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export function isPasskeyCancellation(error: unknown): boolean {
  return (
    error instanceof DOMException &&
    (error.name === 'NotAllowedError' || error.name === 'AbortError')
  );
}

export function passkeyErrorMessage(error: unknown, fallback = 'Passkey sign-in failed.'): string {
  if (error instanceof DOMException) {
    if (isPasskeyCancellation(error)) return 'Passkey sign-in was cancelled.';
    if (error.name === 'InvalidStateError') return 'This passkey is already registered.';
    if (error.name === 'SecurityError') return 'Passkeys are not allowed on this site.';
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export function getDeviceName(): string {
  if (typeof navigator === 'undefined') return 'Unknown device';
  const ua = navigator.userAgent;
  const platform = /Mac/.test(ua) ? 'Mac'
    : /Win/.test(ua) ? 'Windows'
    : /Linux/.test(ua) ? 'Linux'
    : /Android/.test(ua) ? 'Android'
    : /iPhone|iPad/.test(ua) ? 'iOS' : 'Unknown';
  const browser = /Firefox/.test(ua) ? 'Firefox'
    : /Edg/.test(ua) ? 'Edge'
    : /Chrome/.test(ua) ? 'Chrome'
    : /Safari/.test(ua) ? 'Safari' : 'Browser';
  return `${platform} - ${browser}`;
}

function jwtSubject(accessToken: string): string | undefined {
  try {
    const payload = accessToken.split('.')[1];
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    return (JSON.parse(json) as { sub?: string }).sub;
  } catch {
    return undefined;
  }
}

async function requestChallenge(issuer: string, clientId: string): Promise<string> {
  const res = await fetch(passkeyEndpoint(issuer, clientId, 'challenge'), {
    method: 'GET', credentials: 'include', cache: 'no-store',
  });
  if (!res.ok) throw new Error(`Passkey challenge failed (${res.status})`);
  const data = (await res.json().catch(() => undefined)) as { challenge?: string } | undefined;
  if (!data?.challenge) throw new Error("Passkey challenge response missing 'challenge'");
  return data.challenge;
}

export interface PasskeyTokens {
  accessToken: string;
  refreshToken: string | null;
  idToken: string | null;
  expiresAt: number; // unix seconds
}

const SILENT_REDIRECT_PATH = '/silent-check-sso.html';

/**
 * Authenticate with a discoverable passkey, then — exactly like the React app —
 * silently exchange the resulting Keycloak SSO session for OIDC tokens via a
 * hidden `prompt=none` iframe (no full-page redirect, no hosted login page).
 */
export async function loginWithPasskey(
  issuer: string, clientId: string, rpId: string = defaultRpId(),
): Promise<PasskeyTokens> {
  if (!isPasskeySupported()) throw new Error('This browser does not support passkeys.');
  const challenge = await requestChallenge(issuer, clientId);
  const credential = await navigator.credentials.get({
    publicKey: {
      challenge: fromBase64Url(challenge) as BufferSource,
      rpId,
      userVerification: 'required',
      timeout: CEREMONY_TIMEOUT_MS,
    },
  });
  if (!(credential instanceof PublicKeyCredential)) throw new Error('No passkey credential was returned.');
  const response = credential.response;
  if (!(response instanceof AuthenticatorAssertionResponse) || !response.userHandle) {
    throw new Error('Unexpected passkey authentication response.');
  }
  const authRes = await fetch(passkeyEndpoint(issuer, clientId, 'authenticate'), {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
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
  // for the client silently, without showing the hosted login page.
  return silentTokenExchange(issuer, clientId);
}

// ── Silent token retrieval (prompt=none authorization-code + PKCE) ───────────

async function pkcePair(): Promise<{ verifier: string; challenge: string }> {
  const rand = new Uint8Array(32);
  crypto.getRandomValues(rand);
  const verifier = toBase64Url(rand.buffer);
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return { verifier, challenge: toBase64Url(digest) };
}

async function silentTokenExchange(issuer: string, clientId: string): Promise<PasskeyTokens> {
  const base = issuer.replace(/\/+$/, '');
  const authorizationEndpoint = `${base}/protocol/openid-connect/auth`;
  const tokenEndpoint = `${base}/protocol/openid-connect/token`;
  const redirectUri = `${window.location.origin}${SILENT_REDIRECT_PATH}`;
  const { verifier, challenge } = await pkcePair();
  const state = crypto.randomUUID();
  const nonce = crypto.randomUUID();

  const authUrl =
    `${authorizationEndpoint}?` +
    new URLSearchParams({
      client_id: clientId,
      redirect_uri: redirectUri,
      response_type: 'code',
      scope: 'openid profile email',
      prompt: 'none',
      code_challenge: challenge,
      code_challenge_method: 'S256',
      state,
      nonce,
    }).toString();

  const code = await codeFromSilentIframe(authUrl, redirectUri, state);

  const tokenRes = await fetch(tokenEndpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: clientId,
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
    idToken: data.id_token ?? null,
    expiresAt: Math.floor(Date.now() / 1000) + (data.expires_in ?? 300),
  };
}

// Loads the prompt=none auth URL in a hidden iframe; silent-check-sso.html posts
// the redirected URL (carrying ?code) back to us. Resolves with the auth code.
function codeFromSilentIframe(authUrl: string, redirectUri: string, state: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const iframe = document.createElement('iframe');
    iframe.style.display = 'none';
    let settled = false;

    const cleanup = () => {
      window.removeEventListener('message', onMessage);
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
      if (typeof event.data !== 'string' || !event.data.startsWith(redirectUri)) return;
      const params = new URL(event.data).searchParams;
      if (params.get('state') !== state) return fail('Silent login state mismatch.');
      const err = params.get('error');
      if (err) return fail(`Silent login failed: ${err}`);
      const code = params.get('code');
      if (!code) return fail('Silent login returned no authorization code.');
      settled = true;
      cleanup();
      resolve(code);
    };

    const timer = setTimeout(() => fail('Silent login timed out.'), CEREMONY_TIMEOUT_MS);
    window.addEventListener('message', onMessage);
    iframe.src = authUrl;
    document.body.appendChild(iframe);
  });
}

/** Registers a new passkey for the currently logged-in user. */
export async function registerPasskey(
  issuer: string, clientId: string, accessToken: string,
  rpId: string = defaultRpId(), rpName = 'Logos',
): Promise<void> {
  if (!isPasskeySupported()) throw new Error('This browser does not support passkeys.');
  const sub = jwtSubject(accessToken);
  if (!sub) throw new Error('Cannot register a passkey: access token has no subject.');
  const challenge = await requestChallenge(issuer, clientId);
  const credential = await navigator.credentials.create({
    publicKey: {
      challenge: fromBase64Url(challenge) as BufferSource,
      rp: { name: rpName, id: rpId },
      user: {
        id: new TextEncoder().encode(sub) as BufferSource,
        name: getDeviceName(),
        displayName: getDeviceName(),
      },
      pubKeyCredParams: [{ type: 'public-key', alg: -7 }, { type: 'public-key', alg: -257 }],
      authenticatorSelection: { residentKey: 'required', userVerification: 'required' },
      timeout: CEREMONY_TIMEOUT_MS,
    },
  });
  if (!(credential instanceof PublicKeyCredential)) throw new Error('No passkey credential was returned.');
  const response = credential.response;
  if (!(response instanceof AuthenticatorAttestationResponse)) {
    throw new Error('Unexpected passkey registration response.');
  }
  const saveRes = await fetch(passkeyEndpoint(issuer, clientId, 'save'), {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
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
