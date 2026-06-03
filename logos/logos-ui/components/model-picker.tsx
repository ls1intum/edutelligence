import React, { useState, useRef } from "react";
import { Modal, Pressable, ScrollView, TouchableWithoutFeedback, View } from "react-native";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { Input, InputField } from "@/components/ui/input";

type Model = { id: number; name: string };

type ModelPickerProps = {
  models: Model[];
  selectedId: string;
  onSelect: (id: string) => void;
  excludedIds?: string[];
  placeholder?: string;
};

export function ModelPicker({
  models,
  selectedId,
  onSelect,
  excludedIds = [],
  placeholder = "Select model...",
}: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [dropdownPos, setDropdownPos] = useState({ top: 0, left: 0, width: 0 });
  const triggerRef = useRef<View>(null);

  const selectedModel = models.find((m) => String(m.id) === selectedId);

  const filtered = models
    .filter(
      (m) => !excludedIds.includes(String(m.id)) || String(m.id) === selectedId
    )
    .filter((m) => m.name.toLowerCase().includes(search.toLowerCase()));

  const handleOpen = () => {
    if (open) {
      setOpen(false);
      setSearch("");
      return;
    }
    triggerRef.current?.measureInWindow((x, y, width, height) => {
      const dropdownHeight = 210;
      const viewportHeight =
        typeof window !== "undefined" ? window.innerHeight : 9999;
      const spaceBelow = viewportHeight - (y + height + 4);
      const top =
        spaceBelow >= dropdownHeight
          ? y + height + 4
          : Math.max(8, y - dropdownHeight - 4);
      setDropdownPos({ top, left: x, width });
      setOpen(true);
    });
  };

  const handleClose = () => {
    setOpen(false);
    setSearch("");
  };

  const handleSelect = (id: string) => {
    onSelect(id);
    handleClose();
  };

  return (
    <View ref={triggerRef}>
      <Pressable
        onPress={handleOpen}
        className={`flex-row items-center justify-between rounded-md border bg-white px-3 py-2 dark:bg-[#1b1b1b] ${
          open
            ? "border-blue-500"
            : "border-outline-200 dark:border-outline-700"
        }`}
      >
        <Text
          className={`text-sm ${
            selectedModel
              ? "text-black dark:text-white"
              : "text-gray-500 dark:text-gray-400"
          }`}
        >
          {selectedModel?.name ?? placeholder}
        </Text>
      </Pressable>

      {open && (
        <Modal transparent animationType="none" onRequestClose={handleClose}>
          <View style={{ flex: 1 }}>
            <TouchableWithoutFeedback onPress={handleClose}>
              <View style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }} />
            </TouchableWithoutFeedback>

            <View
              style={{
                position: "absolute",
                top: dropdownPos.top,
                left: dropdownPos.left,
                width: dropdownPos.width,
                borderRadius: 6,
                borderWidth: 1,
                borderColor: "#e2e8f0",
                backgroundColor: "#ffffff",
                overflow: "hidden",
                shadowColor: "#000",
                shadowOffset: { width: 0, height: 4 },
                shadowOpacity: 0.15,
                shadowRadius: 6,
                elevation: 10,
              }}
            >
              <Box className="border-b border-outline-100 p-2 dark:border-outline-800">
                <Input className="h-8 border-outline-200 bg-gray-50 dark:border-outline-700 dark:bg-[#111]">
                  <InputField
                    placeholder="Search models..."
                    value={search}
                    onChangeText={setSearch}
                    className="text-xs text-black dark:text-white"
                    autoFocus
                  />
                </Input>
              </Box>

              <ScrollView
                style={{ maxHeight: 160 }}
                nestedScrollEnabled
                keyboardShouldPersistTaps="handled"
              >
                {filtered.length === 0 ? (
                  <Text className="p-3 text-xs text-gray-500 dark:text-gray-400">
                    No models found.
                  </Text>
                ) : (
                  filtered.map((m) => {
                    const isSelected = String(m.id) === selectedId;
                    return (
                      <Pressable
                        key={m.id}
                        onPress={() => handleSelect(String(m.id))}
                        className={`border-b border-outline-100 px-3 py-2 last:border-b-0 dark:border-outline-800 ${
                          isSelected
                            ? "bg-blue-50 dark:bg-blue-900/20"
                            : "bg-transparent"
                        }`}
                      >
                        <Text
                          className={`text-sm ${
                            isSelected
                              ? "font-semibold text-blue-600 dark:text-blue-400"
                              : "font-normal text-black dark:text-white"
                          }`}
                        >
                          {m.name}
                        </Text>
                      </Pressable>
                    );
                  })
                )}
              </ScrollView>
            </View>
          </View>
        </Modal>
      )}
    </View>
  );
}
