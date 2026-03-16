import React from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";

type SegmentedSwitchOption = {
  label: string;
  value: string | boolean;
};

type SegmentedSwitchProps = {
  options: [SegmentedSwitchOption, SegmentedSwitchOption];
  value: string | boolean;
  onChange: (value: string | boolean) => void;
};

function SegmentedSwitch({ options, value, onChange }: SegmentedSwitchProps) {
  return (
    <View className="flex-row self-start overflow-hidden rounded-full border border-outline-300 bg-background-50 p-0.5">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <Pressable
            key={String(option.value)}
            onPress={() => onChange(option.value)}
            className={[
              "min-h-0 rounded-full px-4 py-1.5 border-2 border-transparent web:cursor-pointer web:transition-colors web:duration-200 web:ease-out",
              active
                ? "bg-info-600 hover:bg-info-700"
                : "bg-transparent dark:hover:bg-background-100 hover:bg-background-100 hover:border-outline-400",
            ].join(" ")}
          >
            {({ hovered }) => (
              <Text
                className={[
                  "text-sm",
                  active
                    ? "font-semibold text-typography-0"
                    : hovered
                      ? "font-medium text-typography-700"
                      : "font-medium text-typography-600",
                ].join(" ")}
              >
                {option.label}
              </Text>
            )}
          </Pressable>
        );
      })}
    </View>
  );
}

export default SegmentedSwitch;
