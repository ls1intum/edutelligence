export const KEYCLOAK_ISSUER =
  process.env.EXPO_PUBLIC_KEYCLOAK_ISSUER ?? "http://localhost:8085/realms/tum";

export const KEYCLOAK_CLIENT_ID =
  process.env.EXPO_PUBLIC_KEYCLOAK_CLIENT_ID ?? "logos";

export const oidcEndpoints = {
  authorizationEndpoint: `${KEYCLOAK_ISSUER}/protocol/openid-connect/auth`,
  tokenEndpoint: `${KEYCLOAK_ISSUER}/protocol/openid-connect/token`,
  endSessionEndpoint: `${KEYCLOAK_ISSUER}/protocol/openid-connect/logout`,
};

export type StoredTokens = {
  accessToken: string;
  refreshToken: string | null;
  expiresAt: number;
};

export const TOKEN_STORAGE_KEY = "logos_kc_tokens";
