import React from 'react';
import { Linking, Pressable } from 'react-native';
import { Link } from "expo-router";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { HStack } from "@/components/ui/hstack";

export default function Footer() {
  const openExternal = (url: string) => Linking.openURL(url);

  return (
    <Box className="w-full p-3 border-t border-outline-200 bg-background-light dark:bg-[#2a2a2a] dark:border-outline-700">
      <Box className="self-center w-[80%] flex-row justify-between items-center">
          <HStack space="md">
              <Link href="/about" asChild>
                <Text className="text-gray-500 font-semibold">About</Text>
              </Link>
              <Pressable onPress={() => openExternal('https://github.com/ls1intum/edutelligence')}>
                <Text className="text-gray-500 font-semibold">Releases</Text>
              </Pressable>
              <Link href="/privacy" asChild>
                <Text className="text-gray-500 font-semibold">Privacy</Text>
              </Link>
              <Link href="/imprint" asChild>
                <Text className="text-gray-500 font-semibold">Imprint</Text>
              </Link>
          </HStack>
          <Text className="text-right text-sm text-gray-500">
            Built by{' '}
            <Text className="text-[#969696] font-semibold" onPress={() => openExternal('https://github.com/flbrgit')}>
              Florian Briksa
            </Text>{' '}
            at{' '}
            <Text className="text-[#969696] font-semibold" onPress={() => openExternal('https://www.tum.de/en/')}>
              TUM
            </Text>
            . The source code is available on{' '}
            <Text className="text-[#969696] font-semibold" onPress={() => openExternal('https://github.com/ls1intum/edutelligence')}>
              Github
            </Text>
            .
          </Text>
      </Box>
    </Box>
  );
}
