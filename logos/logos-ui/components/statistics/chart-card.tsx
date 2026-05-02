import React, { useState } from "react";
import { Platform, View } from "react-native";

import { Text } from "@/components/ui/text";

type ChartCardProps = {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
  children: (width: number) => React.ReactNode;
  className?: string;
};

export default function ChartCard({
  title,
  subtitle,
  right,
  children,
  className,
}: ChartCardProps) {
  const [layoutWidth, setLayoutWidth] = useState(0);
  const [hovered, setHovered] = useState(false);

  const isWeb = Platform.OS === "web";
  const hoverProps = isWeb
    ? {
        onMouseEnter: () => setHovered(true),
        onMouseLeave: () => setHovered(false),
      }
    : {};

  // Card stretches vertically to match siblings in the same flex row, so
  // a row never has uneven heights. The body fills any extra space below
  // the header — content there is packed at the top by default.
  const baseStyle: any = {
    alignSelf: "stretch",
    flexGrow: 1,
    flexShrink: 1,
    display: "flex",
    flexDirection: "column",
  };
  const webStyle: any = isWeb
    ? {
        ...baseStyle,
        transitionProperty:
          "background-color, border-color, box-shadow, transform",
        transitionDuration: "220ms",
        transitionTimingFunction: "ease",
        transform: hovered ? "translateY(-1px)" : "translateY(0)",
      }
    : baseStyle;

  return (
    <View
      {...(hoverProps as any)}
      className={`w-full overflow-hidden rounded-2xl border bg-background-0 shadow-soft-1 ${
        hovered ? "border-outline-300" : "border-outline-200"
      } ${className || ""}`}
      style={webStyle}
      onLayout={(e) => {
        const w = e.nativeEvent.layout.width;
        if (Math.abs(w - layoutWidth) > 1) setLayoutWidth(w);
      }}
    >
      <View
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "flex-start",
          justifyContent: "space-between",
          columnGap: 12,
          paddingHorizontal: 18,
          paddingTop: 14,
          paddingBottom: 10,
        }}
      >
        <View
          style={{
            display: "flex",
            flexDirection: "column",
            minWidth: 0,
            flexGrow: 1,
            flexShrink: 1,
            flexBasis: 0,
          }}
        >
          <Text
            className="text-typography-900"
            style={{ fontSize: 15, fontWeight: "600" }}
          >
            {title}
          </Text>
          {subtitle ? (
            <Text
              className="text-typography-500"
              style={{ fontSize: 12, marginTop: 2 }}
            >
              {subtitle}
            </Text>
          ) : null}
        </View>
        {right ? (
          <View
            style={{
              display: "flex",
              flexDirection: "row",
              flexWrap: "wrap",
              alignItems: "center",
              justifyContent: "flex-end",
              flexShrink: 0,
              columnGap: 8,
              rowGap: 4,
            }}
          >
            {right}
          </View>
        ) : null}
      </View>

      <View
        style={{
          paddingHorizontal: 18,
          paddingBottom: 18,
          flexGrow: 1,
          flexShrink: 1,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {layoutWidth > 0 ? (
          children(Math.max(0, layoutWidth - 36))
        ) : (
          <View style={{ height: 200 }} />
        )}
      </View>
    </View>
  );
}
