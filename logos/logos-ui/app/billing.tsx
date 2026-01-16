import React from "react";

import { useAuth } from "@/components/auth-shell";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";

export default function Billing() {
  useAuth();
  return (
    <VStack className="w-full flex-1">
      <Text
        size="2xl"
        className="mb-6 text-center font-bold text-black dark:text-white"
      >
        Billing Management
      </Text>
      <Box className="mt-5 self-center rounded-3xl border border-gray-400 p-5">
        <Text className="text-black dark:text-white">
          Hier erscheinen bald Kosten...
        </Text>
      </Box>
    </VStack>
  );
}
