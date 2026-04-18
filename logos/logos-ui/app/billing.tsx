import React from "react";

import { useAuth } from "@/components/auth-shell";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";

export default function Billing() {
  useAuth();
  return (
    <VStack className="w-full" space="lg">
      <Text
        size="2xl"
        className="text-center font-bold text-black dark:text-white"
      >
        Billing Management
      </Text>
      <Box className="self-center rounded-2xl border border-outline-200 p-5 dark:border-outline-800 dark:bg-[#111]">
        <Text className="text-gray-500 self-center dark:text-gray-400">Coming soon</Text>
      </Box>
    </VStack>
  );
}
