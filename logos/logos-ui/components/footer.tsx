import React from 'react';
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { HStack } from "@/components/ui/hstack";

export default function Footer() {
  return (
    <Box className="w-full p-3 border-t border-outline-200 bg-background-light dark:bg-[#2a2a2a] dark:border-outline-700">
      <Box className="self-center w-[80%] flex-row justify-between items-center">
          <HStack space="md">
              <Text className="text-gray-500">
                <a href="/about" style={{ textDecoration: 'none', color: 'inherit' }}><b>About</b></a>
              </Text>
              <Text className="text-gray-500">
                <a href="https://github.com/ls1intum/edutelligence" style={{ textDecoration: 'none', color: 'inherit' }}><b>Releases</b></a>
              </Text>
              <Text className="text-gray-500">
                <a href="/privacy" style={{ textDecoration: 'none', color: 'inherit' }}><b>Privacy</b></a>
              </Text>
              <Text className="text-gray-500">
                <a href="/imprint" style={{ textDecoration: 'none', color: 'inherit' }}><b>Imprint</b></a>
              </Text>
          </HStack>
          <Text className="text-right text-sm">
            Built by <a href="https://github.com/flbrgit" style={{ color: '#969696' }}><b>Florian Briksa</b></a> at <a href="https://www.tum.de/en/" style={{ color: '#969696' }}><b>TUM</b></a>.
            The source code is available on <a href="https://github.com/ls1intum/edutelligence" style={{ color: '#969696' }}><b>Github</b></a>.
          </Text>
      </Box>
    </Box>
  );
}
