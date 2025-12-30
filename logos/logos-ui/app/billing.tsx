import React from 'react';

import { useAuth } from '@/components/auth-shell';
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";

export default function Billing() {
    useAuth();
    return (
        <VStack className="flex-1 w-full">
            <Text size="2xl" className="font-bold mb-6 text-center text-black dark:text-white">
                Billing Management
            </Text>
            <Box className="mt-5 p-5 rounded-3xl border border-gray-400 self-center">
                <Text className="text-black dark:text-white">
                    Hier erscheinen bald Kosten...
                </Text>
            </Box>
        </VStack>
    );
}
