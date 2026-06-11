import React from "react";
import { Linking, Pressable } from "react-native";
import { router } from "expo-router";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { HStack } from "@/components/ui/hstack";

export default function Footer() {
  const openExternal = (url: string) => Linking.openURL(url);

  return (
    <Box className="w-full border-t border-outline-200 bg-background-light p-3 dark:border-outline-700 dark:bg-[#2a2a2a]">
      <Box className="w-[80%] flex-row items-center justify-between self-center">
        <HStack space="md">
          <Pressable onPress={() => router.push("/about")}>
            <Text className="font-semibold text-gray-500">About</Text>
          </Pressable>
          <Pressable
            onPress={() =>
              openExternal("https://github.com/ls1intum/edutelligence")
            }
          >
            <Text className="font-semibold text-gray-500">Releases</Text>
          </Pressable>
          <Pressable onPress={() => router.push("/privacy")}>
            <Text className="font-semibold text-gray-500">Privacy</Text>
          </Pressable>
          <Pressable onPress={() => router.push("/imprint")}>
            <Text className="font-semibold text-gray-500">Imprint</Text>
          </Pressable>
        </HStack>
        <Text className="text-right text-sm text-gray-500">The source code is available on{" "}
          <Text
            className="font-semibold text-[#969696]"
            onPress={() =>
              openExternal("https://github.com/ls1intum/edutelligence")
            }
          >
            Github
          </Text>
          .
        </Text>
      </Box>
    </Box>
  );
}
