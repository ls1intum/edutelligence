import Keycloak from 'keycloak-js';
import { InjectionToken } from '@angular/core';

export const KEYCLOAK = new InjectionToken<Keycloak>('KEYCLOAK');

let instance: Keycloak | null = null;

/** Passkey config served by /api/info (#632). Empty => fall back to hostname/"Logos". */
export interface PasskeyConfig { rpId?: string; rpName?: string; }
let passkeyConfig: PasskeyConfig = {};

/** Returns the initialized singleton; throws if init has not run. */
export function getKeycloak(): Keycloak {
  if (!instance) throw new Error('Keycloak not initialized');
  return instance;
}

/** WebAuthn RP id/name from /api/info; both optional (see #632). */
export function getPasskeyConfig(): PasskeyConfig {
  return passkeyConfig;
}

/** Splits a Keycloak issuer `{url}/realms/{realm}` into `[url, realm]`. */
export function splitIssuer(issuer: string): [string, string] {
  const marker = '/realms/';
  const i = issuer.indexOf(marker);
  if (i < 0) throw new Error(`Issuer is not in {url}/realms/{realm} form: ${issuer}`);
  const url = issuer.slice(0, i);
  const realm = issuer.slice(i + marker.length).replace(/\/+$/, '');
  if (!realm) throw new Error(`Issuer has no realm: ${issuer}`);
  return [url, realm];
}

/** Reconstructs the issuer URL from a configured keycloak-js instance. */
export function keycloakIssuer(kc: Keycloak): string {
  const url = (kc.authServerUrl ?? '').replace(/\/+$/, '');
  return `${url}/realms/${kc.realm}`;
}

/**
 * Fetches runtime config from /api/info and initializes the keycloak-js
 * singleton with check-sso + PKCE. Must run before the app renders.
 */
export async function initKeycloak(): Promise<Keycloak> {
  const res = await fetch('/api/info');
  if (!res.ok) throw new Error(`Failed to load runtime config from /api/info: ${res.status}`);
  const data = (await res.json()) as {
    keycloak?: { issuer?: string; client_id?: string; passkey_rp_id?: string; passkey_rp_name?: string };
  };
  const issuer = data.keycloak?.issuer;
  const clientId = data.keycloak?.client_id;
  if (!issuer || !clientId) {
    throw new Error('Server /api/info response missing keycloak.issuer or keycloak.client_id');
  }
  // #632: shared TUM Keycloak serves the parent-domain RP id so passkeys work
  // across *.aet.cit.tum.de. Blank => the ceremony falls back to the hostname.
  passkeyConfig = {
    rpId: data.keycloak?.passkey_rp_id || undefined,
    rpName: data.keycloak?.passkey_rp_name || undefined,
  };
  const [url, realm] = splitIssuer(issuer);
  const kc = new Keycloak({ url, realm, clientId });
  // The "iframe ... can escape its sandboxing" console warning is emitted by
  // keycloak-js itself (keycloak.js #checkSsoSilently / #check3pCookiesSupported),
  // which hardcodes sandbox="allow-scripts allow-same-origin" on its hidden
  // iframes. It is benign here: those iframes load only the trusted IdP and our
  // own same-origin /silent-check-sso.html. Removing it would require patching
  // the dependency, so we leave the warning as-is.
  await kc.init({
    onLoad: 'check-sso',
    pkceMethod: 'S256',
    silentCheckSsoRedirectUri: window.location.origin + '/silent-check-sso.html',
    checkLoginIframe: false,
  });
  kc.onTokenExpired = () => { void kc.updateToken(30); };
  instance = kc;
  return kc;
}
