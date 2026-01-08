import "../global.css";
import React, { useState } from "react";
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
  const pathname = usePathname();

  const isPublic = (() => {
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
            <Box className="min-h-screen flex-1 bg-white dark:bg-[#1e1e1e]">
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
