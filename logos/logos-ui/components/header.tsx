import React, { useState, useEffect } from "react";
import { Image as ExpoImage } from "expo-image";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { HStack } from "@/components/ui/hstack";
import { Pressable } from "react-native";
import { Moon, Sun } from "lucide-react-native";
import { useRouter } from "expo-router";

type HeaderProps = {
  colorMode?: "light" | "dark";
  onToggleColorMode?: () => void;
};

export default function Header({
  colorMode = "light",
  onToggleColorMode,
}: HeaderProps) {
  const router = useRouter();
  const [hue, setHue] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setHue((h) => (h + 1) % 360);
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <Box className="w-full flex-row items-center justify-between border-b border-outline-200 px-6 py-3">
      <HStack className="w-full items-center justify-between">
        <Box className="flex-row items-center">
          <Pressable onPress={() => router.push("/")}>
            <ExpoImage
              source={require("../assets/images/logos_full.png")}
              style={
                {
                  width: 160,
                  height: 72,
                  filter: `hue-rotate(${hue}deg)`,
                } as any
              }
              contentFit="contain"
            />
          </Pressable>
          <Text size="xl" className="ml-4 text-gray-500">
            0.0.4
          </Text>
        </Box>
        <Pressable
          onPress={onToggleColorMode}
          disabled={!onToggleColorMode}
          className="rounded-full border bg-secondary-950 p-2 dark:bg-secondary-500"
          accessibilityLabel="Toggle color mode"
        >
          {colorMode === "dark" ? (
            <Sun size={28} color="#facc15" strokeWidth={2.5} />
          ) : (
            <Moon size={28} color="#334155" strokeWidth={2.5} />
          )}
        </Pressable>
      </HStack>
    </Box>
  );
}
