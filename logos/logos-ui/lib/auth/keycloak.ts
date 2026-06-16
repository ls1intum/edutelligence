const ISSUER_FROM_ENV = process.env.EXPO_PUBLIC_KEYCLOAK_ISSUER;
const CLIENT_ID_FROM_ENV = process.env.EXPO_PUBLIC_KEYCLOAK_CLIENT_ID;

// Outside of `expo start` (development) the app must be built with the real
// Keycloak endpoints baked in — silently falling back to localhost in
// production would route every login to a non-existent server.
if (!__DEV__ && (!ISSUER_FROM_ENV || !CLIENT_ID_FROM_ENV)) {
  throw new Error(
    "Missing EXPO_PUBLIC_KEYCLOAK_ISSUER or EXPO_PUBLIC_KEYCLOAK_CLIENT_ID — required for non-dev builds.",
  );
}

export const KEYCLOAK_ISSUER =
  ISSUER_FROM_ENV ?? "http://localhost:8085/realms/tum";

export const KEYCLOAK_CLIENT_ID = CLIENT_ID_FROM_ENV ?? "logos";

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
