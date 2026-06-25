import "../global.css";
import React, { useEffect, useState } from "react";
import { usePathname } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { StyleSheet, View } from "react-native";
import { Slot } from "expo-router";

import { GluestackUIProvider } from "@/components/ui/gluestack-ui-provider";
import "@/global.css";
import { AuthenticatedShell, AuthProvider } from "@/components/auth-shell";
import Header from "@/components/header";
import { Box } from "@/components/ui/box";
import Footer from "@/components/footer";

export default function _layout() {
  const [colorMode, setColorMode] = useState<"light" | "dark">("light");
  const [hydrated, setHydrated] = useState(false);
  const pathname = usePathname();

  useEffect(() => setHydrated(true), []);

  // The web build is a single-page export: every route serves the same SSG HTML,
  // which was pre-rendered with pathname === "/" (isPublic === true). Until React
  // has finished hydrating, treat every route as public so the first client render
  // matches the server HTML; otherwise we get React error #418 on direct loads of
  // protected routes like /statistics.
  const isPublic =
    !hydrated ||
    (() => {
      const current = pathname || "/";
      return (
        current === "/" ||
        current.startsWith("/about") ||
        current.startsWith("/imprint") ||
        current.startsWith("/privacy")
      );
    })();

  console.log(
    "[_layout] rendering, pathname:",
    pathname,
    "isPublic:",
    isPublic
  );

  return (
    <AuthProvider>
      <GluestackUIProvider mode={colorMode}>
        <SafeAreaView style={[styles.safeArea]}>
          <View style={styles.container}>
            <Box suppressHydrationWarning className="min-h-screen flex-1 bg-white dark:bg-[#1e1e1e]">
              <Header
                colorMode={colorMode}
                onToggleColorMode={() =>
                  setColorMode(colorMode === "light" ? "dark" : "light")
                }
              />
              {isPublic ? (
                <Slot />
              ) : (
                <AuthenticatedShell>
                  <Slot />
                </AuthenticatedShell>
              )}
              <Footer />
            </Box>
          </View>
        </SafeAreaView>
      </GluestackUIProvider>
    </AuthProvider>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  container: {
    flex: 1,
  },
});
