import React from 'react';

import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";

export default function Settings() {
  return (
    <VStack className="w-full">
      <Text size="2xl" className="font-bold text-center text-black dark:text-white">
        Settings
      </Text>
      <Text className="text-center text-gray-500 dark:text-gray-300">
        Configure your Logos experience.
      </Text>
      <Box className="mt-4 p-5 rounded-2xl border border-outline-200 dark:border-outline-800 bg-gray-50 dark:bg-[#111] self-center">
        <Text className="text-black dark:text-white">
          Hier erscheinen bald Einstellungen...
        </Text>
      </Box>
    </VStack>
  );
}
