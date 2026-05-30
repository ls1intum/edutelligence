import React, { useEffect, useState } from "react";
import { Pressable, ScrollView } from "react-native";
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
import {
  Select,
  SelectBackdrop,
  SelectContent,
  SelectInput,
  SelectItem,
  SelectPortal,
  SelectTrigger,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableData,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ActivityIndicator } from "react-native";

const privacyOptions = [
  "LOCAL",
  "CLOUD_IN_EU_BY_US_PROVIDER",
  "CLOUD_NOT_IN_EU_BY_US_PROVIDER",
  "CLOUD_IN_EU_BY_EU_PROVIDER",
];

const providerTypeOptions = ["logosnode", "azure", "cloud"];

const cloudProviderTypeOptions = [
  "azure",
  "openai",
  "anthropic",
  "gemini",
  "bedrock",
  "deepseek",
  "groq",
  "none",
];

type Provider = {
  id: number;
  name: string;
  base_url: string;
  auth_name: string;
  auth_format: string;
  provider_type: string;
  cloud_provider_type: string | null;
  privacy_level: string;
};

type EditState = {
  provider_id: number;
  name: string;
  base_url: string;
  api_key: string;
  auth_name: string;
  auth_format: string;
  provider_type: string;
  cloud_provider_type: string;
  privacy_level: string;
};

export default function Providers() {
  const { apiKey } = useAuth();
  const [stats, setStats] = useState<{
    totalProviders: number;
    mostUsedProvider: string;
  } | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);

  const [editProvider, setEditProvider] = useState<EditState | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Provider | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const router = useRouter();

  useEffect(() => {
    if (!apiKey) return;
    loadProviders(apiKey);
    loadStats(apiKey);
  }, [apiKey]);

  const loadProviders = async (key: string) => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE}/logosdb/get_providers`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          logos_key: key,
        },
        body: JSON.stringify({
          logos_key: key,
        }),
      });

      const result = await response.json();
      const [data, code] = Array.isArray(result)
        ? result
        : [result, response.status];

      if (code === 200 && Array.isArray(data)) {
        const formattedProviders = data.map((p: any) => ({
          id: p.id,
          name: p.name,
          base_url: p.base_url,
          auth_name: p.auth_name,
          auth_format: p.auth_format,
          provider_type: p.provider_type,
          cloud_provider_type: p.cloud_provider_type,
          privacy_level: p.privacy_level,
        }));
        setProviders(formattedProviders);
      } else {
        setProviders([]);
      }
    } catch (e) {
      setProviders([]);
    } finally {
      setLoading(false);
    }
  };

  const loadStats = async (key: string) => {
    try {
      const response = await fetch(
        `${API_BASE}/logosdb/get_general_provider_stats`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            logos_key: key,
          },
          body: JSON.stringify({
            logos_key: key,
          }),
        }
      );
      const result = await response.json();
      const [data, code] = Array.isArray(result)
        ? result
        : [result, response.status];

      if (code === 200) {
        setStats(data);
      } else {
        setStats({ totalProviders: 0, mostUsedProvider: "None" });
      }
    } catch (e) {
      setStats({ totalProviders: 0, mostUsedProvider: "None" });
    }
  };

  const openEdit = (provider: Provider) => {
    setEditProvider({
      provider_id: provider.id,
      name: provider.name ?? "",
      base_url: provider.base_url ?? "",
      api_key: "",
      auth_name: provider.auth_name ?? "",
      auth_format: provider.auth_format ?? "",
      provider_type: provider.provider_type ?? "cloud",
      cloud_provider_type: provider.cloud_provider_type ?? "none",
      privacy_level: provider.privacy_level ?? "LOCAL",
    });
    setSaveMsg(null);
  };

  const closeEdit = () => {
    setEditProvider(null);
    setSaveMsg(null);
  };

  const handleSave = async () => {
    if (!editProvider || !apiKey) return;
    setSaving(true);
    setSaveMsg(null);

    const payload = {
      logos_key: apiKey,
      provider_id: editProvider.provider_id,
      name: editProvider.name || undefined,
      base_url: editProvider.base_url || undefined,
      api_key: editProvider.api_key || undefined,
      auth_name: editProvider.auth_name || undefined,
      auth_format: editProvider.auth_format || undefined,
      provider_type: editProvider.provider_type || undefined,
      cloud_provider_type:
        editProvider.cloud_provider_type === "none"
          ? null
          : editProvider.cloud_provider_type,
      privacy_level: editProvider.privacy_level || undefined,
    };

    try {
      const res = await fetch(`${API_BASE}/logosdb/update_provider`, {
        method: "POST",
        headers: { "Content-Type": "application/json", logos_key: apiKey },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setSaveMsg(body.error ?? "Save failed.");
        return;
      }

      setSaveMsg("Saved.");
      loadProviders(apiKey);
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
    setProviders((prev) => prev.filter((p) => p.id !== id));
    try {
      await fetch(`${API_BASE}/logosdb/delete_provider`, {
        method: "POST",
        headers: { "Content-Type": "application/json", logos_key: apiKey },
        body: JSON.stringify({ logos_key: apiKey, provider_id: id }),
      });
    } catch {
      loadProviders(apiKey);
    }
  };

  return (
    <VStack className="w-full" space="lg">
      <VStack className="items-center space-y-1">
        <Text
          size="2xl"
          className="text-center font-bold text-black dark:text-white"
        >
          Providers
        </Text>
        <Text className="text-center text-gray-500 dark:text-gray-300">
          Administrate providers.
        </Text>
      </VStack>

      {stats && (
        <HStack space="xl" className="justify-center">
          <VStack className="min-w-[120px] items-center rounded-xl border border-outline-200 bg-background-50 p-4 dark:border-none">
            <Text size="xl" className="font-bold text-black dark:text-white">
              {stats.totalProviders}
            </Text>
            <Text size="sm" className="mt-1 text-black dark:text-white">
              Provider(s)
            </Text>
          </VStack>
          <VStack className="min-w-[120px] items-center rounded-xl border border-outline-200 bg-background-50 p-4 dark:border-none">
            <Text size="xl" className="font-bold text-black dark:text-white">
              {stats.mostUsedProvider}
            </Text>
            <Text size="sm" className="mt-1 text-black dark:text-white">
              Most frequently used
            </Text>
          </VStack>
        </HStack>
      )}

      <Box className="self-end">
        <Button onPress={() => router.push("/add_provider")}>
          <ButtonText>+ Add</ButtonText>
        </Button>
      </Box>

      {loading ? (
        <VStack space="lg" className="items-center justify-center p-8">
          <ActivityIndicator size="large" color="#006DFF" />
          <Text className="mt-2 text-gray-500">Loading providers...</Text>
        </VStack>
      ) : (
        <Box className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-2">
          <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
            <Box className="min-w-full">
              <Table className="w-full bg-secondary-200">
                <TableHeader>
                  <TableRow className="bg-secondary-200">
                    <TableHead>Name</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Privacy</TableHead>
                    <TableHead>Base URL</TableHead>
                    <TableHead>{""}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {providers.map((provider) => (
                    <TableRow key={provider.id} className="bg-secondary-200">
                      <TableData>
                        <Pressable onPress={() => openEdit(provider)}>
                          <Text style={{ fontWeight: "500" }}>
                            {provider.name}
                          </Text>
                        </Pressable>
                      </TableData>
                      <TableData>
                        <Text style={{ fontSize: 12 }}>
                          {provider.provider_type}
                        </Text>
                      </TableData>
                      <TableData>
                        <Text style={{ fontSize: 12 }}>
                          {provider.privacy_level
                            ?.replace("CLOUD_", "")
                            .replace(/_/g, " ") ?? "-"}
                        </Text>
                      </TableData>
                      <TableData>
                        <Text style={{ fontSize: 12 }}>
                          {provider.base_url}
                        </Text>
                      </TableData>
                      <TableData style={{ width: 72 }}>
                        <HStack space="xs" style={{ alignItems: "center" }}>
                          <Pressable
                            onPress={() => openEdit(provider)}
                            style={{ padding: 8 }}
                          >
                            <Icon
                              as={EditIcon}
                              size="sm"
                              className="text-typography-400"
                            />
                          </Pressable>
                          <Pressable
                            onPress={() => setDeleteTarget(provider)}
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
        visible={editProvider !== null}
        onClose={closeEdit}
        maxWidth={500}
        cardStyle={{ maxHeight: "90%", padding: 0 }}
      >
        <ScrollView
          contentContainerStyle={{ padding: 24 }}
          showsVerticalScrollIndicator={true}
        >
          <Text style={{ fontWeight: "700", fontSize: 18, marginBottom: 16 }}>
            Edit Provider
          </Text>

          {editProvider && (
            <VStack space="md">
              <EditField
                label="Name"
                value={editProvider.name}
                onChangeText={(v) =>
                  setEditProvider({ ...editProvider, name: v })
                }
              />
              <EditField
                label="Base URL"
                value={editProvider.base_url}
                onChangeText={(v) =>
                  setEditProvider({ ...editProvider, base_url: v })
                }
              />
              <EditField
                label="API Key (Leave blank to keep unchanged)"
                value={editProvider.api_key}
                placeholder="sk-..."
                onChangeText={(v) =>
                  setEditProvider({ ...editProvider, api_key: v })
                }
              />

              <HStack space="sm">
                <Box style={{ flex: 1 }}>
                  <EditField
                    label="Auth Header Name"
                    value={editProvider.auth_name}
                    placeholder="Authorization"
                    onChangeText={(v) =>
                      setEditProvider({ ...editProvider, auth_name: v })
                    }
                  />
                </Box>
                <Box style={{ flex: 1 }}>
                  <EditField
                    label="Auth Format"
                    value={editProvider.auth_format}
                    placeholder="Bearer {}"
                    onChangeText={(v) =>
                      setEditProvider({ ...editProvider, auth_format: v })
                    }
                  />
                </Box>
              </HStack>

              <FieldLabel label="Provider Type" />
              <Select
                selectedValue={editProvider.provider_type}
                onValueChange={(v) =>
                  setEditProvider({
                    ...editProvider,
                    provider_type: v || "cloud",
                  })
                }
              >
                <SelectTrigger>
                  <SelectInput
                    placeholder="Select type"
                    value={editProvider.provider_type}
                  />
                </SelectTrigger>
                <SelectPortal>
                  <SelectBackdrop />
                  <SelectContent>
                    {providerTypeOptions.map((opt) => (
                      <SelectItem key={opt} label={opt} value={opt} />
                    ))}
                  </SelectContent>
                </SelectPortal>
              </Select>

              <FieldLabel label="Cloud Provider (Optional)" />
              <Select
                selectedValue={editProvider.cloud_provider_type}
                onValueChange={(v) =>
                  setEditProvider({
                    ...editProvider,
                    cloud_provider_type: v || "none",
                  })
                }
              >
                <SelectTrigger>
                  <SelectInput
                    placeholder="Select cloud provider"
                    value={editProvider.cloud_provider_type}
                  />
                </SelectTrigger>
                <SelectPortal>
                  <SelectBackdrop />
                  <SelectContent>
                    {cloudProviderTypeOptions.map((opt) => (
                      <SelectItem key={opt} label={opt} value={opt} />
                    ))}
                  </SelectContent>
                </SelectPortal>
              </Select>

              <FieldLabel label="Privacy Level" />
              <Select
                selectedValue={editProvider.privacy_level}
                onValueChange={(v) =>
                  setEditProvider({
                    ...editProvider,
                    privacy_level: v || "LOCAL",
                  })
                }
              >
                <SelectTrigger>
                  <SelectInput
                    placeholder="Select privacy"
                    value={editProvider.privacy_level}
                  />
                </SelectTrigger>
                <SelectPortal>
                  <SelectBackdrop />
                  <SelectContent>
                    {privacyOptions.map((opt) => (
                      <SelectItem key={opt} label={opt} value={opt} />
                    ))}
                  </SelectContent>
                </SelectPortal>
              </Select>

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
        title="Delete Provider?"
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
  placeholder,
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  placeholder?: string;
}) => {
  return (
    <VStack space="xs">
      <FieldLabel label={label} />
      <Input>
        <InputField
          value={value}
          onChangeText={onChangeText}
          placeholder={placeholder}
        />
      </Input>
    </VStack>
  );
};
