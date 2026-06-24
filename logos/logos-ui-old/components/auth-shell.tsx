import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { ScrollView } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { usePathname, useRouter } from "expo-router";
import * as AuthSession from "expo-auth-session";

import Main from "@/components/main";
import { Box } from "@/components/ui/box";
import { HStack } from "@/components/ui/hstack";
import { VStack } from "@/components/ui/vstack";
import { ActivityIndicator, Pressable, Text } from "react-native";
import Sidebar from "./sidebar";
import { API_BASE } from "@/components/statistics/constants";
import { HOME_ROUTE, isRouteAllowed, UserRole } from "@/components/route-permissions";
import {
  fetchKeycloakConfig,
  KeycloakConfig,
  StoredTokens,
  TOKEN_STORAGE_KEY,
} from "@/lib/auth/keycloak";

export type Team = { id: number; name: string };

type AuthContextValue = {
  apiKey: string;
  status: "checking" | "authenticated" | "unauthenticated";
  configError: boolean;
  reloadConfig: () => Promise<void>;
  keycloak: KeycloakConfig | null;
  role: UserRole | null;
  userId: number | null;
  teams: Team[];
  roleError: boolean;
  reloadRole: () => Promise<void>;
  completeLogin: (tokens: StoredTokens) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue>({
  apiKey: "",
  status: "checking",
  configError: false,
  reloadConfig: async () => { },
  keycloak: null,
  role: null,
  userId: null,
  teams: [],
  roleError: false,
  reloadRole: async () => { },
  completeLogin: async () => { },
  logout: async () => { },
});

export const useAuth = () => useContext(AuthContext);

type AuthProviderProps = {
  children: React.ReactNode;
};

export function AuthProvider({ children }: AuthProviderProps) {
  const [tokens, setTokens] = useState<StoredTokens | null>(null);
  const [status, setStatus] = useState<"checking" | "authenticated" | "unauthenticated">("checking");
  const [role, setRole] = useState<UserRole | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [roleError, setRoleError] = useState(false);
  const [keycloak, setKeycloak] = useState<KeycloakConfig | null>(null);
  const [configError, setConfigError] = useState(false);

  const apiKey = tokens?.accessToken ?? "";

  const loadConfig = useCallback(async () => {
    try {
      const cfg = await fetchKeycloakConfig();
      setKeycloak(cfg);
      setConfigError(false);
    } catch (e) {
      console.error("[auth] failed to load runtime config", e);
      setConfigError(true);
    }
  }, []);

  const reloadConfig = useCallback(async () => {
    setConfigError(false);
    await loadConfig();
  }, [loadConfig]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  const clearSession = useCallback(async () => {
    await AsyncStorage.removeItem(TOKEN_STORAGE_KEY);
    setTokens(null);
    setRole(null);
    setUserId(null);
    setTeams([]);
    setRoleError(false);
    setStatus("unauthenticated");
  }, []);

  const fetchRole = useCallback(
    async (accessToken: string) => {
      try {
        const res = await fetch(`${API_BASE}/me`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        });
        if (res.ok) {
          const data = await res.json();
          setRole(data.role as UserRole);
          setUserId(data.user_id ?? null);
          setTeams(data.teams ?? []);
          setRoleError(false);
        } else {
          await clearSession();
        }
      } catch {
        setRoleError(true);
      }
    },
    [clearSession]
  );

  const reloadRole = useCallback(async () => {
    if (!apiKey) return;
    setRoleError(false);
    await fetchRole(apiKey);
  }, [apiKey, fetchRole]);

  const persistTokens = useCallback(
    async (next: StoredTokens) => {
      await AsyncStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify(next));
      setTokens(next);
      setStatus("authenticated");
      await fetchRole(next.accessToken);
    },
    [fetchRole]
  );

  const refreshTokens = useCallback(
    async (current: StoredTokens) => {
      if (!keycloak) return;
      if (!current.refreshToken) {
        await clearSession();
        return;
      }
      try {
        const result = await AuthSession.refreshAsync(
          { clientId: keycloak.clientId, refreshToken: current.refreshToken },
          keycloak.endpoints
        );
        await persistTokens({
          accessToken: result.accessToken,
          refreshToken: result.refreshToken ?? current.refreshToken,
          expiresAt: Math.floor(Date.now() / 1000) + (result.expiresIn ?? 300),
        });
      } catch (e) {
        console.error("[auth] token refresh failed", e);
        await clearSession();
      }
    },
    [keycloak, persistTokens, clearSession]
  );

  useEffect(() => {
    // Wait until the runtime config is loaded before deciding the auth state.
    if (!keycloak) return;
    let isMounted = true;
    (async () => {
      const raw = await AsyncStorage.getItem(TOKEN_STORAGE_KEY);
      if (!isMounted) return;
      if (!raw) {
        setStatus("unauthenticated");
        return;
      }
      try {
        const stored: StoredTokens = JSON.parse(raw);
        if (stored.expiresAt * 1000 > Date.now() + 30_000) {
          setTokens(stored);
          setStatus("authenticated");
          await fetchRole(stored.accessToken);
        } else {
          await refreshTokens(stored);
        }
      } catch {
        await clearSession();
      }
    })();
    return () => {
      isMounted = false;
    };
  }, [keycloak, fetchRole, refreshTokens, clearSession]);

  useEffect(() => {
    if (!tokens?.refreshToken) return;
    const ms = tokens.expiresAt * 1000 - Date.now() - 60_000;
    const timer = setTimeout(() => refreshTokens(tokens), Math.max(ms, 10_000));
    return () => clearTimeout(timer);
  }, [tokens, refreshTokens]);

  const logout = useCallback(async () => {
    try {
      if (keycloak && tokens?.refreshToken) {
        await fetch(keycloak.endpoints.endSessionEndpoint, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: new URLSearchParams({
            client_id: keycloak.clientId,
            refresh_token: tokens.refreshToken,
          }).toString(),
        });
      }
    } catch {
    }
    await clearSession();
  }, [keycloak, tokens, clearSession]);

  const value = useMemo(
    () => ({
      apiKey, status, configError, reloadConfig, keycloak,
      role, userId, teams, roleError, reloadRole,
      completeLogin: persistTokens, logout,
    }),
    [apiKey, status, configError, reloadConfig, keycloak,
     role, userId, teams, roleError, reloadRole, persistTokens, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

type AuthenticatedShellProps = {
  children: React.ReactNode | ((apiKey: string) => React.ReactNode);
  contentClassName?: string;
  colorMode?: "light" | "dark";
  onToggleColorMode?: () => void;
};

export function AuthenticatedShell({
  children,
  contentClassName,
}: AuthenticatedShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { apiKey, status, role, roleError, reloadRole, configError, reloadConfig, keycloak } = useAuth();

  useEffect(() => {
    if (!role || !pathname) return;
    if (!isRouteAllowed(role, pathname)) {
      router.replace(HOME_ROUTE[role] as any);
    }
  }, [role, pathname, router]);

  if (configError) {
    return (
      <Box className="min-h-screen flex-1 items-center justify-center bg-white dark:bg-[#1e1e1e]">
        <Text className="mb-4 text-gray-500">Couldn't load runtime configuration.</Text>
        <Pressable
          onPress={() => reloadConfig()}
          className="rounded-md bg-[#006DFF] px-4 py-2"
        >
          <Text className="text-white">Retry</Text>
        </Pressable>
      </Box>
    );
  }

  if (!keycloak || status === "checking") {
    return (
      <Box className="min-h-screen flex-1 items-center justify-center bg-white dark:bg-[#1e1e1e]">
        <ActivityIndicator size="large" color="#006DFF" />
        <Text className="mt-4 text-gray-500">Checking authentication...</Text>
      </Box>
    );
  }

  if (status === "unauthenticated") {
    return (
      <Box className="min-h-screen flex-1 bg-white dark:bg-[#1e1e1e]">
        <Main
          redirectTo={pathname ?? "/dashboard"}
          enableAutoRedirect={false}
        />
      </Box>
    );
  }

  if (!role) {
    if (roleError) {
      return (
        <Box className="min-h-screen flex-1 items-center justify-center bg-white dark:bg-[#1e1e1e]">
          <Text className="mb-4 text-gray-500">Couldn't load your profile.</Text>
          <Pressable
            onPress={() => reloadRole()}
            className="rounded-md bg-[#006DFF] px-4 py-2"
          >
            <Text className="text-white">Retry</Text>
          </Pressable>
        </Box>
      );
    }
    return (
      <Box className="min-h-screen flex-1 items-center justify-center bg-white dark:bg-[#1e1e1e]">
        <ActivityIndicator size="large" color="#006DFF" />
        <Text className="mt-4 text-gray-500">Loading...</Text>
      </Box>
    );
  }

  const content =
    typeof children === "function"
      ? (children as (key: string) => React.ReactNode)(apiKey)
      : children;

  console.log("[AuthShell] Rendering content (Sidebar + Children)");

  return (
    <HStack className="flex-1 items-start">
      <Sidebar />
      <ScrollView
        className="h-full flex-1"
        contentContainerStyle={{ flexGrow: 1, paddingBottom: 32 }}
      >
        <VStack
          className={`min-h-full w-full p-6 md:p-8 ${contentClassName ?? ""}`}
        >
          {content}
        </VStack>
      </ScrollView>
    </HStack>
  );
}
