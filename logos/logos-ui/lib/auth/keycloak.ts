import { API_BASE } from "@/components/statistics/constants";

// Keycloak config is fetched from the server at runtime (see /api/info) so the
// web bundle does not have to be rebuilt to point at a different Keycloak
// instance. Nothing here is statically baked into the bundle.

export type OidcEndpoints = {
  authorizationEndpoint: string;
  tokenEndpoint: string;
  endSessionEndpoint: string;
};

export type KeycloakConfig = {
  issuer: string;
  clientId: string;
  endpoints: OidcEndpoints;
  // WebAuthn Relying Party ID for passkeys. Must be a registrable suffix of the
  // UI origin AND match what the passkey was registered with in Keycloak. On the
  // shared TUM Keycloak this is the parent domain (e.g. `aet.cit.tum.de`) so a
  // passkey works across all `*.aet.cit.tum.de` apps — not the full UI host.
  // Empty/undefined => fall back to the current hostname (fine for localhost).
  passkeyRpId?: string;
  passkeyRpName?: string;
};

export type StoredTokens = {
  accessToken: string;
  refreshToken: string | null;
  expiresAt: number;
};

export const TOKEN_STORAGE_KEY = "logos_kc_tokens";

export async function fetchKeycloakConfig(): Promise<KeycloakConfig> {
  const res = await fetch(`${API_BASE}/info`);
  if (!res.ok) {
    throw new Error(`Failed to load runtime config from /info: ${res.status}`);
  }
  const data = (await res.json()) as {
    keycloak?: {
      issuer?: string;
      client_id?: string;
      passkey_rp_id?: string;
      passkey_rp_name?: string;
    };
  };
  const issuer = data.keycloak?.issuer;
  const clientId = data.keycloak?.client_id;
  if (!issuer || !clientId) {
    throw new Error("Server /info response missing keycloak.issuer or keycloak.client_id");
  }
  return {
    issuer,
    clientId,
    passkeyRpId: data.keycloak?.passkey_rp_id || undefined,
    passkeyRpName: data.keycloak?.passkey_rp_name || undefined,
    endpoints: {
      authorizationEndpoint: `${issuer}/protocol/openid-connect/auth`,
      tokenEndpoint: `${issuer}/protocol/openid-connect/token`,
      endSessionEndpoint: `${issuer}/protocol/openid-connect/logout`,
    },
  };
}

// Endpoint of the custom Keycloak passkey provider, mounted per-client at
// `{issuer}/passkey/{clientId}/{path}`, where `path` is one of:
// health | challenge | authenticate | save.
export function passkeyEndpoint(cfg: KeycloakConfig, path: string): string {
  const base = cfg.issuer.replace(/\/+$/, "");
  return `${base}/passkey/${encodeURIComponent(cfg.clientId)}/${path}`;
}
