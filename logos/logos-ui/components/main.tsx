import * as WebBrowser from "expo-web-browser";
import { useAuthRequest, makeRedirectUri } from "expo-auth-session";
import * as Crypto from "expo-crypto";
import { usePathname, useRouter } from "expo-router";
import React, { useEffect, useRef, useState } from "react";
import { Alert } from "react-native";
import { Image as ExpoImage } from "expo-image";

function parseJwtPayload(token: string): Record<string, unknown> {
  try {
    const b64 = token.split(".")[1];
    const b64std = b64
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(b64.length + (4 - (b64.length % 4)) % 4, "=");
    return JSON.parse(atob(b64std)) as Record<string, unknown>;
  } catch {
    return {};
  }
}

import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { Button, ButtonText } from "@/components/ui/button";
import { VStack } from "@/components/ui/vstack";
import { Center } from "@/components/ui/center";
import { useAuth } from "@/components/auth-shell";
import type { KeycloakConfig, StoredTokens } from "@/lib/auth/keycloak";
import { isPasskeySupported, loginWithPasskey, passkeyErrorMessage } from "@/lib/auth/passkey";

WebBrowser.maybeCompleteAuthSession();

type MainProps = {
  redirectTo?: string | null;
  onAuthenticated?: (key: string) => void;
  enableAutoRedirect?: boolean;
};

export default function Main(props: MainProps = {}) {
  const { status, keycloak, configError, reloadConfig } = useAuth();

  if (configError) {
    return (
      <Center className="flex-1 bg-white p-6 dark:bg-[#1e1e1e]">
        <VStack space="md" className="items-center">
          <Text className="text-black dark:text-white">Couldn't load runtime configuration.</Text>
          <Button onPress={() => reloadConfig()}>
            <ButtonText>Retry</ButtonText>
          </Button>
        </VStack>
      </Center>
    );
  }

  if (!keycloak || status === "checking") {
    return (
      <Center className="flex-1 bg-white dark:bg-[#1e1e1e]">
        <Text className="text-black dark:text-white">Checking login…</Text>
      </Center>
    );
  }

  // keycloak is non-null beyond this point — useAuthRequest gets stable inputs.
  return <LoginView {...props} keycloak={keycloak} />;
}

type LoginViewProps = MainProps & { keycloak: KeycloakConfig };

function LoginView({
  redirectTo = "/dashboard",
  onAuthenticated,
  enableAutoRedirect = true,
  keycloak,
}: LoginViewProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { status, apiKey, completeLogin } = useAuth();
  const hasNavigatedRef = useRef(false);
  const nonceRef = useRef(Crypto.randomUUID());

  const [hue, setHue] = useState(0);
  const [mounted, setMounted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [passkeyLoading, setPasskeyLoading] = useState(false);
  const passkeyAvailable = isPasskeySupported();

  const handlePasskeyLogin = async () => {
    setPasskeyLoading(true);
    try {
      const tokens = await loginWithPasskey(keycloak);
      await completeLogin(tokens);
      onAuthenticated?.(tokens.accessToken);
      const target = redirectTo === null ? null : (redirectTo ?? "/dashboard");
      hasNavigatedRef.current = true;
      if (target && target !== pathname) router.replace(target);
    } catch (err: unknown) {
      Alert.alert("Passkey sign-in failed", passkeyErrorMessage(err));
    } finally {
      setPasskeyLoading(false);
    }
  };

  const redirectUri = makeRedirectUri({ scheme: "logos", path: "auth" });

  const [request, response, promptAsync] = useAuthRequest(
    {
      clientId: keycloak.clientId,
      redirectUri,
      scopes: ["openid", "profile", "email"],
      usePKCE: true,
      extraParams: { nonce: nonceRef.current },
    },
    { authorizationEndpoint: keycloak.endpoints.authorizationEndpoint }
  );

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const interval = setInterval(() => setHue((h) => (h + 1) % 360), 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!enableAutoRedirect) return;
    if (status !== "authenticated") return;
    if (pathname !== "/") return;
    if (hasNavigatedRef.current) return;

    const target = redirectTo === null ? null : (redirectTo ?? "/dashboard");
    hasNavigatedRef.current = true;
    if (target && target !== pathname) router.replace(target);
    if (apiKey) onAuthenticated?.(apiKey);
  }, [status, enableAutoRedirect, redirectTo, pathname, router, apiKey, onAuthenticated]);

  useEffect(() => {
    if (!response) return;
    if (response.type !== "success") {
      setLoading(false);
      if (response.type === "error") {
        Alert.alert("Login failed", response.error?.message ?? "Authorization error");
      }
      return;
    }
    const { code } = response.params;
    if (!code || !request?.codeVerifier) {
      setLoading(false);
      return;
    }

    const exchange = async () => {
      try {
        const body = new URLSearchParams({
          grant_type: "authorization_code",
          client_id: keycloak.clientId,
          code,
          code_verifier: request.codeVerifier!,
          redirect_uri: redirectUri,
        });
        const res = await fetch(keycloak.endpoints.tokenEndpoint, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: body.toString(),
        });
        if (!res.ok) throw new Error(`Token exchange failed: ${res.status}`);
        const data = await res.json();
        if (data.id_token) {
          const payload = parseJwtPayload(data.id_token as string);
          if (payload.nonce !== nonceRef.current) {
            throw new Error("id_token nonce mismatch, possible replay attack");
          }
        }
        const tokens: StoredTokens = {
          accessToken: data.access_token,
          refreshToken: data.refresh_token ?? null,
          expiresAt: Math.floor(Date.now() / 1000) + (data.expires_in ?? 300),
        };
        await completeLogin(tokens);
        onAuthenticated?.(tokens.accessToken);
        const target = redirectTo === null ? null : (redirectTo ?? "/dashboard");
        hasNavigatedRef.current = true;
        if (target && target !== pathname) router.replace(target);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Unknown error";
        Alert.alert("Login failed", message);
      } finally {
        setLoading(false);
      }
    };
    void exchange();
  }, [response, request, redirectUri, completeLogin, onAuthenticated, redirectTo, pathname, router, keycloak]);

  if (status === "authenticated") {
    return (
      <Center className="flex-1">
        <Text className="text-black dark:text-white">Login successful</Text>
      </Center>
    );
  }

  return (
    <Center className="flex-1 bg-white p-6 dark:bg-[#1e1e1e]">
      <VStack space="xl" className="w-full max-w-[500px] items-center">
        <ExpoImage
          source={require("../assets/images/logos_full.png")}
          style={
            { width: 200, height: 90, filter: `hue-rotate(${mounted ? hue : 0}deg)` } as any
          }
          contentFit="contain"
        />
        <Text size="2xl" className="mb-4 text-center font-bold text-black dark:text-white">
          Sign in to your account
        </Text>
        <Box className="w-1/2 min-w-[300px]">
          <VStack space="md">
            <Button
              onPress={() => {
                setLoading(true);
                void promptAsync();
              }}
              isDisabled={!request || loading || passkeyLoading}
              className="w-full"
            >
              <ButtonText>{loading ? "Signing in…" : "Sign in with Keycloak"}</ButtonText>
            </Button>
            {passkeyAvailable && (
              <Button
                variant="outline"
                onPress={() => void handlePasskeyLogin()}
                isDisabled={loading || passkeyLoading}
                className="w-full"
              >
                <ButtonText>
                  {passkeyLoading ? "Waiting for passkey…" : "Sign in with a passkey"}
                </ButtonText>
              </Button>
            )}
          </VStack>
        </Box>
      </VStack>
    </Center>
  );
}
