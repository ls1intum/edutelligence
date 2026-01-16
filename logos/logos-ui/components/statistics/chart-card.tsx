import React, { useState } from "react";
import { View } from "react-native";

import { Text } from "@/components/ui/text";

type ChartCardProps = {
  title: string;
  subtitle?: string;
  children: (width: number) => React.ReactNode;
  className?: string;
};

export default function ChartCard({
  title,
  subtitle,
  children,
  className,
}: ChartCardProps) {
  const [layoutWidth, setLayoutWidth] = useState(0);

  return (
    <View
      className={`my-2.5 rounded-2xl bg-secondary-200 p-4 shadow-hard-2 ${
        className || ""
      }`}
      onLayout={(e) => {
        const w = e.nativeEvent.layout.width;
        if (Math.abs(w - layoutWidth) > 1) setLayoutWidth(w);
      }}
    >
      <View className="mb-5">
        <Text className="text-lg font-semibold text-typography-900">
          {title}
        </Text>
        {subtitle && (
          <Text className="mt-1 text-xs text-typography-600">{subtitle}</Text>
        )}
      </View>
      {layoutWidth > 0 ? (
        children(layoutWidth - 32)
      ) : (
        <View style={{ height: 200 }} />
      )}
    </View>
  );
}
