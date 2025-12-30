import React from 'react';

import { useAuth } from '@/components/auth-shell';
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";

export default function Statistics() {
  useAuth();
  return (
    <VStack className="w-full space-y-4">
      <Text size="2xl" className="font-bold text-center text-black dark:text-white">
        Statistics
      </Text>
      <Text className="text-center text-gray-500 dark:text-gray-300">
        Detailed overview of model usage, performance, billing, quality, and system metrics.
      </Text>
      <Box className="mt-4 p-5 rounded-2xl border border-outline-200 dark:border-outline-800 bg-gray-50 dark:bg-[#111] self-center space-y-2">
        <Text className="text-black dark:text-white">- Model Usage</Text>
        <Text className="text-black dark:text-white">- Performance Metrics</Text>
        <Text className="text-black dark:text-white">- Billing Overview</Text>
        <Text className="text-black dark:text-white">- Quality & Feedback</Text>
        <Text className="text-black dark:text-white">- (Optional) System Metrics</Text>
      </Box>
    </VStack>
  );
}
