import React, { useEffect, useRef, useState } from "react";
import { FlatList, Pressable, ScrollView, TouchableOpacity } from "react-native";
import { useRouter } from "expo-router";

import { useAuth } from "@/components/auth-shell";
import { API_BASE } from "@/components/statistics/constants";
import { BaseModal } from "@/components/modals/base-modal";
import { ConfirmDeleteModal } from "@/components/modals/confirm-delete-modal";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonText } from "@/components/ui/button";
import { Input, InputField } from "@/components/ui/input";
import { Icon, EditIcon, TrashIcon } from "@/components/ui/icon";
import { Select, SelectBackdrop, SelectContent, SelectInput, SelectItem, SelectPortal, SelectTrigger } from "@/components/ui/select";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableData,
} from "@/components/ui/table";
import { ActivityIndicator } from "react-native";

type EditState = {
  model_id: number;
  name: string;
  description: string;
  tags: string;
  parallel: string;
  weight_latency: string;
  weight_accuracy: string;
  weight_cost: string;
  weight_quality: string;
};

export default function Models() {
  const { apiKey } = useAuth();
  const [stats, setStats] = useState<{
    totalModels: number;
    mostUsedModel: string;
  } | null>(null);
  const [models, setModels] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [editModel, setEditModel] = useState<EditState | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<any | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    if (!apiKey) return;
    loadModels(apiKey);
    loadStats(apiKey);
  }, [apiKey]);

  const loadModels = async (key: string) => {
    try {
      setLoading(true);
      const response = await fetch(
        `${API_BASE}/logosdb/get_models`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${key}`,
          },
          body: JSON.stringify({
            logos_key: key,
          }),
        }
      );
      const data = await response.json();
      if (Array.isArray(data)) {
        setModels(data);
      } else {
        setModels([]);
      }
    } catch (e) {
      setModels([]);
    } finally {
      setLoading(false);
    }
  };

  const loadStats = async (key: string) => {
    try {
      const response = await fetch(
        `${API_BASE}/logosdb/get_general_model_stats`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${key}`,
          },
          body: JSON.stringify({
            logos_key: key,
          }),
        }
      );
      const data = await response.json();
      setStats(Array.isArray(data) ? data[0] : data);
    } catch (e) {
      setStats({ totalModels: 0, mostUsedModel: "None" });
    }
  };

  const openEdit = (model: any) => {
    setEditModel({
      model_id: model.id,
      name: model.name ?? "",
      description: model.description ?? "",
      tags: model.tags ?? "",
      parallel: String(model.parallel ?? 1),
      weight_latency: model.weight_latency != null ? String(model.weight_latency) : "",
      weight_accuracy: model.weight_accuracy != null ? String(model.weight_accuracy) : "",
      weight_cost: model.weight_cost != null ? String(model.weight_cost) : "",
      weight_quality: model.weight_quality != null ? String(model.weight_quality) : "",
      input_usd_per_million: model.input_usd_per_million != null ? String(model.input_usd_per_million) : "",
      output_usd_per_million: model.output_usd_per_million != null ? String(model.output_usd_per_million) : "",
    });
    setSaveMsg(null);
  };

  const closeEdit = () => {
    setEditModel(null);
    setSaveMsg(null);
  };

  const handleSave = async () => {
    if (!editModel || !apiKey) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      const res = await fetch(`${API_BASE}/logosdb/update_model_info`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({
          logos_key: apiKey,
          model_id: editModel.model_id,
          name: editModel.name || undefined,
          description: editModel.description || undefined,
          tags: editModel.tags || undefined,
          parallel: editModel.parallel ? parseInt(editModel.parallel, 10) : undefined,
          weight_latency: editModel.weight_latency ? parseInt(editModel.weight_latency, 10) : undefined,
          weight_accuracy: editModel.weight_accuracy ? parseInt(editModel.weight_accuracy, 10) : undefined,
          weight_cost: editModel.weight_cost ? parseInt(editModel.weight_cost, 10) : undefined,
          weight_quality: editModel.weight_quality ? parseInt(editModel.weight_quality, 10) : undefined,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setSaveMsg(body.error ?? "Save failed.");
        return;
      }

      setSaveMsg("Saved.");
      loadModels(apiKey);
      setTimeout(closeEdit, 800);
    } catch {
      setSaveMsg("Unexpected error.");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget || !apiKey) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    setModels(prev => prev.filter(m => m.id !== id));
    try {
      await fetch(`${API_BASE}/logosdb/delete_model`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({ logos_key: apiKey, id }),
      });
    } catch {
      loadModels(apiKey);
    }
  };

  return (
    <VStack className="w-full" space="lg">
      <VStack className="items-center space-y-1">
        <Text
          size="2xl"
          className="text-center font-bold text-black dark:text-white"
        >
          Models
        </Text>
        <Text className="text-center text-gray-500 dark:text-gray-300">
          Administrate Models.
        </Text>
      </VStack>

      {stats && (
        <HStack space="xl" className="justify-center">
          <VStack className="min-w-[120px] items-center rounded-xl border border-outline-200 bg-background-50 p-4 dark:border-none">
            <Text size="xl" className="font-bold text-black dark:text-white">
              {stats.totalModels}
            </Text>
            <Text size="sm" className="mt-1 text-black dark:text-white">
              Models
            </Text>
          </VStack>
          <VStack className="min-w-[120px] items-center rounded-xl border border-outline-200 bg-background-50 p-4 dark:border-none">
            <Text size="xl" className="font-bold text-black dark:text-white">
              {stats.mostUsedModel}
            </Text>
            <Text size="sm" className="mt-1 text-black dark:text-white">
              Most frequently used Model
            </Text>
          </VStack>
        </HStack>
      )}

      <Box className="self-end">
        <Button onPress={() => router.push("/add_model")}>
          <ButtonText>+ Add</ButtonText>
        </Button>
      </Box>

      {loading ? (
        <VStack space="lg" className="items-center justify-center p-8">
          <ActivityIndicator size="large" color="#006DFF" />
          <Text className="mt-2 text-gray-500">Loading models...</Text>
        </VStack>
      ) : (
        <Box className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-2">
          <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
            <Box className="min-w-full">
              <Table className="w-full">
                <TableHeader>
                  <TableRow className="bg-secondary-200">
                    <TableHead>Name</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead>Weights (L/A/C/Q)</TableHead>
                    <TableHead>{""}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {models.map((model) => (
                    <TableRow key={model.id} className="bg-secondary-200">
                      <TableData>
                        <Pressable onPress={() => openEdit(model)}>
                          <Text style={{ fontWeight: "500" }}>
                            {model.name}
                          </Text>
                        </Pressable>
                      </TableData>
                      <TableData>
                        <Text
                          style={{ fontSize: 12, color: "#666" }}
                          numberOfLines={1}
                        >
                          {model.description || "-"}
                        </Text>
                      </TableData>
                      <TableData>
                        <Text style={{ fontSize: 12, color: "#666" }}>
                          L:{model.weight_latency ?? "-"} A:
                          {model.weight_accuracy ?? "-"} C:
                          {model.weight_cost ?? "-"} Q:
                          {model.weight_quality ?? "-"}
                        </Text>
                      </TableData>
                      <TableData style={{ width: 72 }}>
                        <HStack space="xs" style={{ alignItems: "center" }}>
                          <Pressable
                            onPress={() => openEdit(model)}
                            style={{ padding: 8 }}
                          >
                            <Icon
                              as={EditIcon}
                              size="sm"
                              className="text-typography-400"
                            />
                          </Pressable>
                          <Pressable
                            onPress={() => setDeleteTarget(model)}
                            style={{ padding: 8 }}
                          >
                            <Icon
                              as={TrashIcon}
                              size="sm"
                              className="text-typography-400"
                            />
                          </Pressable>
                        </HStack>
                      </TableData>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          </ScrollView>
        </Box>
      )}

      <BaseModal
        visible={editModel !== null}
        onClose={closeEdit}
        maxWidth={500}
        cardStyle={{ maxHeight: "90%", padding: 0 }}
      >
        <ScrollView
          contentContainerStyle={{ padding: 24 }}
          showsVerticalScrollIndicator={true}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={{ fontWeight: "700", fontSize: 18, marginBottom: 16 }}>
            Edit Model
          </Text>

          {editModel && (
            <VStack space="md">
              <EditField
                label="Name"
                value={editModel.name}
                onChangeText={(v) => setEditModel({ ...editModel, name: v })}
                placeholder="gpt-4.1-mini"
              />
              <EditField
                label="Description"
                value={editModel.description}
                onChangeText={(v) =>
                  setEditModel({ ...editModel, description: v })
                }
              />
              <EditField
                label="Tags"
                value={editModel.tags}
                onChangeText={(v) => setEditModel({ ...editModel, tags: v })}
              />
              <EditField
                label="Parallelism"
                value={editModel.parallel}
                keyboardType="numeric"
                onChangeText={(v) =>
                  setEditModel({ ...editModel, parallel: v })
                }
              />

              <Text
                style={{
                  fontWeight: "600",
                  fontSize: 13,
                  color: "#555",
                  marginTop: 8,
                }}
              >
                Compare Weights (model IDs)
              </Text>
              <HStack space="sm">
                <Box style={{ flex: 1 }}>
                  <EditField
                    label="Latency"
                    value={editModel.weight_latency}
                    keyboardType="numeric"
                    onChangeText={(v) =>
                      setEditModel({ ...editModel, weight_latency: v })
                    }
                  />
                </Box>
                <Box style={{ flex: 1 }}>
                  <EditField
                    label="Accuracy"
                    value={editModel.weight_accuracy}
                    keyboardType="numeric"
                    onChangeText={(v) =>
                      setEditModel({ ...editModel, weight_accuracy: v })
                    }
                  />
                </Box>
              </HStack>
              <HStack space="sm">
                <Box style={{ flex: 1 }}>
                  <EditField
                    label="Cost"
                    value={editModel.weight_cost}
                    keyboardType="numeric"
                    onChangeText={(v) =>
                      setEditModel({ ...editModel, weight_cost: v })
                    }
                  />
                </Box>
                <Box style={{ flex: 1 }}>
                  <EditField
                    label="Quality"
                    value={editModel.weight_quality}
                    keyboardType="numeric"
                    onChangeText={(v) =>
                      setEditModel({ ...editModel, weight_quality: v })
                    }
                  />
                </Box>
              </HStack>

              {saveMsg && (
                <Text
                  style={{
                    fontSize: 12,
                    color: saveMsg === "Saved." ? "#22c55e" : "#e63535",
                    marginTop: 4,
                  }}
                >
                  {saveMsg}
                </Text>
              )}

              <HStack
                space="sm"
                style={{ justifyContent: "flex-end", marginTop: 8 }}
              >
                <Button variant="outline" onPress={closeEdit}>
                  <ButtonText>Cancel</ButtonText>
                </Button>
                <Button
                  onPress={handleSave}
                  isDisabled={saving}
                  style={{ opacity: saving ? 0.5 : 1 }}
                >
                  <ButtonText>{saving ? "Saving..." : "Save"}</ButtonText>
                </Button>
              </HStack>
            </VStack>
          )}
        </ScrollView>
      </BaseModal>

      <ConfirmDeleteModal
        visible={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
        title="Delete Model?"
        message={`Are you sure you want to remove "${deleteTarget?.name}"? This action is permanent.`}
      />
    </VStack>
  );
}

const FieldLabel = ({ label }: { label: string }) => (
  <Text style={{ fontSize: 13, fontWeight: "600", color: "#555" }}>
    {label}
  </Text>
);

const EditField = ({
  label,
  value,
  onChangeText,
  keyboardType = "default",
  placeholder,
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  keyboardType?: "default" | "numeric";
  placeholder?: string;
}) => {
  const handleTextChange = (text: string) => {
    if (keyboardType === "numeric") {
      onChangeText(text.replace(/,/g, "."));
    } else {
      onChangeText(text);
    }
  };

  return (
    <VStack space="xs">
      <FieldLabel label={label} />
      <Input>
        <InputField
          value={value}
          onChangeText={handleTextChange}
          keyboardType={keyboardType}
          placeholder={placeholder}
        />
      </Input>
    </VStack>
  );
};
