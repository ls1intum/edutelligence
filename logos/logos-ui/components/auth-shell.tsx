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
import { usePathname } from "expo-router";

import Main from "@/components/main";
import { Box } from "@/components/ui/box";
import { HStack } from "@/components/ui/hstack";
import { VStack } from "@/components/ui/vstack";
import { Center } from "@/components/ui/center";
import { ActivityIndicator, Text } from "react-native";
import Sidebar from "./sidebar";

type AuthContextValue = {
  apiKey: string;
  status: "checking" | "authenticated" | "unauthenticated";
  setApiKey: (key: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue>({
  apiKey: "",
  status: "checking",
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

  const sanitizeKey = useCallback(
    (raw: string | null) => (raw || "").replace(/[\r\n]+/g, "").trim(),
    []
  );

  useEffect(() => {
    let isMounted = true;
    const hydrate = async () => {
      const stored = sanitizeKey(await AsyncStorage.getItem("logos_api_key"));
      if (!isMounted) return;
      if (stored.length) {
        setApiKey(stored);
        setStatus("authenticated");
      } else {
        setStatus("unauthenticated");
      }
    };
    hydrate();
    return () => {
      isMounted = false;
    };
  }, [sanitizeKey]);

  const persistKey = useCallback(
    async (key: string) => {
      const cleaned = sanitizeKey(key);
      await AsyncStorage.setItem("logos_api_key", cleaned);
      setApiKey(cleaned);
      setStatus("authenticated");
    },
    [sanitizeKey]
  );

  const logout = useCallback(async () => {
    await AsyncStorage.removeItem("logos_api_key");
    setApiKey("");
    setStatus("unauthenticated");
    // Routing back to "/" is handled by callers; keep provider focused on state.
  }, []);

  const value = useMemo(
    () => ({
      apiKey,
      status,
      setApiKey: persistKey,
      logout,
    }),
    [apiKey, logout, persistKey, status]
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
  const { apiKey, status, setApiKey } = useAuth();

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
