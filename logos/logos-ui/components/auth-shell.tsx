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

import Main from "@/components/main";
import { Box } from "@/components/ui/box";
import { HStack } from "@/components/ui/hstack";
import { VStack } from "@/components/ui/vstack";
import { ActivityIndicator, Text } from "react-native";
import Sidebar from "./sidebar";
import { API_BASE } from "@/components/statistics/constants";
import { HOME_ROUTE, isRouteAllowed, UserRole } from "@/components/route-permissions";

export type Team = { id: number; name: string };

type AuthContextValue = {
  apiKey: string;
  status: "checking" | "authenticated" | "unauthenticated";
  role: UserRole | null;
  teams: Team[];
  setApiKey: (key: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue>({
  apiKey: "",
  status: "checking",
  role: null,
  teams: [],
  setApiKey: async () => {},
  logout: async () => {},
});

export const useAuth = () => useContext(AuthContext);

type AuthProviderProps = {
  children: React.ReactNode;
};

export function AuthProvider({ children }: AuthProviderProps) {
  const [apiKey, setApiKey] = useState("");
  const [status, setStatus] = useState<
    "checking" | "authenticated" | "unauthenticated"
  >("checking");
  const [role, setRole] = useState<UserRole | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);

  const sanitizeKey = useCallback(
    (raw: string | null) => (raw || "").replace(/[\r\n]+/g, "").trim(),
    []
  );

  const fetchRole = useCallback(async (key: string) => {
      try {
          const res = await fetch(`${API_BASE}/me`, {
              headers: { "logos-key": key },
          });
          if (res.ok) {
              const data = await res.json();
              setRole(data.role as UserRole);
              setTeams(data.teams ?? []);
          } else {
              await AsyncStorage.removeItem("logos_api_key");
              setApiKey("");
              setRole(null);
              setTeams([]);
              setStatus("unauthenticated");
          }
      } catch {
          setRole(null);
          setTeams([]);
      }
  }, []);

  useEffect(() => {
    let isMounted = true;
    const hydrate = async () => {
      const stored = sanitizeKey(await AsyncStorage.getItem("logos_api_key"));
      if (!isMounted) return;
      if (stored.length) {
        setApiKey(stored);
        setStatus("authenticated");
        await fetchRole(stored);
      } else {
        setStatus("unauthenticated");
      }
    };
    hydrate();
    return () => {
      isMounted = false;
    };
  }, [sanitizeKey, fetchRole]);

  const persistKey = useCallback(
    async (key: string) => {
      const cleaned = sanitizeKey(key);
      await AsyncStorage.setItem("logos_api_key", cleaned);
      setApiKey(cleaned);
      setStatus("authenticated");
      await fetchRole(cleaned);
    },
    [sanitizeKey, fetchRole]
  );

  const logout = useCallback(async () => {
    await AsyncStorage.removeItem("logos_api_key");
    setApiKey("");
    setRole(null);
    setTeams([]);
    setStatus("unauthenticated");
    // Routing back to "/" is handled by callers; keep provider focused on state.
  }, []);

  const value = useMemo(
    () => ({
      apiKey,
      status,
      role,
      teams,
      setApiKey: persistKey,
      logout,
    }),
    [apiKey, role, teams, logout, persistKey, status]
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
  const { apiKey, status, role, setApiKey } = useAuth();

  useEffect(() => {
    if (!role || !pathname) return;
    if (!isRouteAllowed(role, pathname)) {
      router.replace(HOME_ROUTE[role] as any);
    }
  }, [role, pathname, router]);

  if (status === "checking") {
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
          onAuthenticated={setApiKey}
          enableAutoRedirect={false}
        />
      </Box>
    );
  }

  if (!role) {
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
