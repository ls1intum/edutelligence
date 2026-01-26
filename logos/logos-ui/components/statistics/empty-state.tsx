import React from "react";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";

export default function EmptyState({ message }: { message: string }) {
  return (
    <Box className="rounded-lg border border-dashed border-outline-300 bg-background-100 p-4">
      <Text className="text-center text-typography-500">{message}</Text>
    </Box>
  );
}
