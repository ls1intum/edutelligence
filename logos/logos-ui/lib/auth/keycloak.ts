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
  const data = (await res.json()) as { keycloak?: { issuer?: string; client_id?: string } };
  const issuer = data.keycloak?.issuer;
  const clientId = data.keycloak?.client_id;
  if (!issuer || !clientId) {
    throw new Error("Server /info response missing keycloak.issuer or keycloak.client_id");
  }
  return {
    issuer,
    clientId,
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
