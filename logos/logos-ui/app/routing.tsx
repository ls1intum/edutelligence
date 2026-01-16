import React from "react";

import { useAuth } from "@/components/auth-shell";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";

export default function Routing() {
  useAuth();
  return (
    <VStack className="w-full space-y-4">
      <Text
        size="2xl"
        className="text-center font-bold text-black dark:text-white"
      >
        Routing Management
      </Text>
      <Text className="text-center text-gray-500 dark:text-gray-300">
        Define and maintain routing rules for your models.
      </Text>
      <Box className="mt-4 self-center rounded-2xl border border-outline-200 bg-gray-50 p-5 dark:border-outline-800 dark:bg-[#111]">
        <Text className="text-black dark:text-white">
          Hier erscheinen bald Routen...
        </Text>
      </Box>
    </VStack>
  );
}
