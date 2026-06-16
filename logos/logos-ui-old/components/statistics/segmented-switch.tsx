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
    <View
      className="flex-row self-start rounded-full border border-outline-200 bg-secondary-100"
      style={{ padding: 3 }}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <Pressable
            key={String(option.value)}
            onPress={() => onChange(option.value)}
            className={[
              "items-center justify-center rounded-full border web:cursor-pointer web:transition-colors web:duration-200 web:ease-out",
              active
                ? "border-outline-200 bg-background-0"
                : "border-transparent web:hover:bg-background-0/40",
            ].join(" ")}
            style={{ height: 30, paddingHorizontal: 14 }}
          >
            {({ hovered }) => (
              <Text
                style={{
                  fontSize: 12,
                  fontWeight: active ? "600" : "500",
                }}
                className={
                  active
                    ? "text-typography-900"
                    : hovered
                      ? "text-typography-700"
                      : "text-typography-500"
                }
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
