import React from "react";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";

export default function EmptyState({ message }: { message: string }) {
  return (
    <Box className="rounded-xl border border-dashed border-outline-200 bg-background-0 p-4">
      <Text className="text-center text-typography-500">{message}</Text>
    </Box>
  );
}
