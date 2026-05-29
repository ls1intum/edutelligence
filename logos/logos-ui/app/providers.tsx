import React, { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView } from "react-native";
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
import {
  Icon,
  EditIcon,
  TrashIcon,
  ChevronDownIcon,
  ChevronUpIcon,
} from "@/components/ui/icon";
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
import { ModelPicker } from "@/components/model-picker";

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
  api_key: string;
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

type ModelConnection = {
  model_id: number;
  model_name: string;
  endpoint: string;
  api_key: string;
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

  const [expandedProviderId, setExpandedProviderId] = useState<number | null>(
    null
  );
  const [providerModels, setProviderModels] = useState<
    Record<number, ModelConnection[]>
  >({});
  const [allModels, setAllModels] = useState<{ id: number; name: string }[]>(
    []
  );

  const [addModelTarget, setAddModelTarget] = useState<Provider | null>(null);
  const [addModelId, setAddModelId] = useState<string>("");
  const [addModelEndpoint, setAddModelEndpoint] = useState("");
  const [addModelApiKey, setAddModelApiKey] = useState("");
  const [addModelSaving, setAddModelSaving] = useState(false);
  const [addModelMsg, setAddModelMsg] = useState<string | null>(null);

  const [editConn, setEditConn] = useState<{
    provider: Provider;
    conn: ModelConnection;
  } | null>(null);
  const [editConnEndpoint, setEditConnEndpoint] = useState("");
  const [editConnApiKey, setEditConnApiKey] = useState("");
  const [editConnSaving, setEditConnSaving] = useState(false);
  const [editConnMsg, setEditConnMsg] = useState<string | null>(null);

  const router = useRouter();

  useEffect(() => {
    if (!apiKey) return;
    loadProviders(apiKey);
    loadStats(apiKey);
  }, [apiKey]);

  useEffect(() => {
    if (!apiKey) return;
    fetch(`${API_BASE}/logosdb/get_models`, {
      method: "POST",
      headers: { "Content-Type": "application/json", logos_key: apiKey },
      body: JSON.stringify({ logos_key: apiKey }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (Array.isArray(data)) setAllModels(data);
      })
      .catch(() => {});
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
          api_key: p.api_key ?? "",
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

  const loadProviderModels = async (providerId: number) => {
    if (!apiKey) return;
    try {
      const res = await fetch(`${API_BASE}/logosdb/get_provider_models`, {
        method: "POST",
        headers: { "Content-Type": "application/json", logos_key: apiKey },
        body: JSON.stringify({ logos_key: apiKey, provider_id: providerId }),
      });
      const data = await res.json();
      if (Array.isArray(data)) {
        setProviderModels((prev) => ({ ...prev, [providerId]: data }));
      }
    } catch {}
  };

  const openEdit = (provider: Provider) => {
    setEditProvider({
      provider_id: provider.id,
      name: provider.name ?? "",
      base_url: provider.base_url ?? "",
      api_key: provider.api_key ?? "",
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

  const toggleExpand = (providerId: number) => {
    if (expandedProviderId === providerId) {
      setExpandedProviderId(null);
    } else {
      setExpandedProviderId(providerId);
      if (!providerModels[providerId]) {
        loadProviderModels(providerId);
      }
    }
  };

  const openAddModel = (provider: Provider) => {
    setAddModelTarget(provider);
    setAddModelId("");
    setAddModelEndpoint("");
    setAddModelApiKey("");
    setAddModelMsg(null);
  };
  const closeAddModel = () => {
    setAddModelTarget(null);
    setAddModelMsg(null);
  };

  const handleAddModel = async () => {
    if (!addModelTarget || !apiKey || !addModelId) return;
    setAddModelSaving(true);
    setAddModelMsg(null);
    try {
      const res = await fetch(`${API_BASE}/logosdb/connect_model_provider`, {
        method: "POST",
        headers: { "Content-Type": "application/json", logos_key: apiKey },
        body: JSON.stringify({
          logos_key: apiKey,
          provider_id: addModelTarget.id,
          model_id: parseInt(addModelId, 10),
          endpoint: addModelEndpoint || null,
          api_key: addModelApiKey || null,
        }),
      });
      if (!res.ok) {
        setAddModelMsg("Failed to connect model.");
        return;
      }
      setAddModelMsg("Connected.");
      await loadProviderModels(addModelTarget.id);
      setTimeout(closeAddModel, 700);
    } catch {
      setAddModelMsg("Unexpected error.");
    } finally {
      setAddModelSaving(false);
    }
  };

  const openEditConn = (provider: Provider, conn: ModelConnection) => {
    setEditConn({ provider, conn });
    setEditConnEndpoint(conn.endpoint);
    setEditConnApiKey(conn.api_key);
    setEditConnMsg(null);
  };
  const closeEditConn = () => {
    setEditConn(null);
    setEditConnMsg(null);
  };

  const handleEditConn = async () => {
    if (!editConn || !apiKey) return;
    setEditConnSaving(true);
    setEditConnMsg(null);
    try {
      const res = await fetch(`${API_BASE}/logosdb/connect_model_provider`, {
        method: "POST",
        headers: { "Content-Type": "application/json", logos_key: apiKey },
        body: JSON.stringify({
          logos_key: apiKey,
          provider_id: editConn.provider.id,
          model_id: editConn.conn.model_id,
          endpoint: editConnEndpoint || null,
          api_key: editConnApiKey || null,
        }),
      });
      if (!res.ok) {
        setEditConnMsg("Save failed.");
        return;
      }
      setEditConnMsg("Saved.");
      await loadProviderModels(editConn.provider.id);
      setTimeout(closeEditConn, 700);
    } catch {
      setEditConnMsg("Unexpected error.");
    } finally {
      setEditConnSaving(false);
    }
  };

  const handleDisconnect = async (
    provider: Provider,
    conn: ModelConnection
  ) => {
    if (!apiKey) return;
    setProviderModels((prev) => ({
      ...prev,
      [provider.id]: (prev[provider.id] ?? []).filter(
        (c) => c.model_id !== conn.model_id
      ),
    }));
    try {
      await fetch(`${API_BASE}/logosdb/disconnect_model_provider`, {
        method: "POST",
        headers: { "Content-Type": "application/json", logos_key: apiKey },
        body: JSON.stringify({
          logos_key: apiKey,
          model_id: conn.model_id,
          provider_id: provider.id,
        }),
      });
    } catch {
      loadProviderModels(provider.id);
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
                  <TableRow className="border-b border-outline-200 bg-secondary-200">
                    <TableHead className="w-10">{""}</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Privacy</TableHead>
                    <TableHead>Base URL</TableHead>
                    <TableHead className="w-20">{""}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {providers.map((provider) => (
                    <React.Fragment key={provider.id}>
                      <TableRow
                        className={`bg-secondary-200 ${
                          expandedProviderId === provider.id
                            ? "border-b-0"
                            : "border-b border-outline-200"
                        }`}
                      >
                        <TableData className="w-10">
                          <Pressable
                            onPress={() => toggleExpand(provider.id)}
                            className="p-2"
                          >
                            <Icon
                              as={
                                expandedProviderId === provider.id
                                  ? ChevronUpIcon
                                  : ChevronDownIcon
                              }
                              size="sm"
                              className="text-typography-400"
                            />
                          </Pressable>
                        </TableData>
                        <TableData>
                          <Pressable onPress={() => openEdit(provider)}>
                            <Text className="font-medium text-black dark:text-white">
                              {provider.name}
                            </Text>
                          </Pressable>
                        </TableData>
                        <TableData>
                          <Text className="text-xs text-gray-700 dark:text-gray-300">
                            {provider.provider_type}
                          </Text>
                        </TableData>
                        <TableData>
                          <Text className="text-xs text-gray-700 dark:text-gray-300">
                            {provider.privacy_level
                              ?.replace("CLOUD_", "")
                              .replace(/_/g, " ") ?? "-"}
                          </Text>
                        </TableData>
                        <TableData>
                          <Text className="text-xs text-gray-700 dark:text-gray-300">
                            {provider.base_url}
                          </Text>
                        </TableData>
                        <TableData className="w-20">
                          <HStack space="xs" className="items-center">
                            <Pressable
                              onPress={() => openEdit(provider)}
                              className="p-2"
                            >
                              <Icon
                                as={EditIcon}
                                size="sm"
                                className="text-typography-400"
                              />
                            </Pressable>
                            <Pressable
                              onPress={() => setDeleteTarget(provider)}
                              className="p-2"
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

                      {expandedProviderId === provider.id && (
                        <TableRow className="border-b border-outline-200 bg-secondary-200">
                          <TableData
                            {...({ colSpan: 6 } as any)}
                            className="p-0"
                          >
                            <Box className="w-full px-14 py-6">
                              <Box className="relative mb-6 w-full flex-row items-center justify-center">
                                <Text className="text-sm font-semibold text-black dark:text-white">
                                  Available Models
                                </Text>
                                <Box className="absolute right-0">
                                  <Button
                                    size="sm"
                                    className="bg-black dark:bg-white"
                                    onPress={() => openAddModel(provider)}
                                  >
                                    <ButtonText className="text-white dark:text-black">
                                      + Connect Model
                                    </ButtonText>
                                  </Button>
                                </Box>
                              </Box>

                              {(providerModels[provider.id] ?? []).length ===
                              0 ? (
                                <Text className="text-center text-xs text-gray-400">
                                  No models connected yet.
                                </Text>
                              ) : (
                                <VStack space="sm">
                                  {(providerModels[provider.id] ?? []).map(
                                    (conn) => (
                                      <HStack
                                        key={conn.model_id}
                                        className="items-center justify-between rounded-lg border border-outline-200 bg-white p-3 dark:border-outline-700 dark:bg-[#1b1b1b]"
                                      >
                                        <Text className="w-1/4 text-sm font-semibold text-black dark:text-white">
                                          {conn.model_name}
                                        </Text>
                                        <Text
                                          className="w-1/3 text-xs text-gray-500 dark:text-gray-400"
                                          numberOfLines={1}
                                        >
                                          {conn.endpoint || "-"}
                                        </Text>
                                        <Text className="font-mono w-1/4 text-xs text-gray-500 dark:text-gray-400">
                                          {conn.api_key
                                            ? `${conn.api_key.slice(0, 4)}…`
                                            : "-"}
                                        </Text>
                                        <HStack className="gap-2">
                                          <Pressable
                                            onPress={() =>
                                              openEditConn(provider, conn)
                                            }
                                            className="p-2"
                                          >
                                            <Icon
                                              as={EditIcon}
                                              size="sm"
                                              className="text-typography-400"
                                            />
                                          </Pressable>
                                          <Pressable
                                            onPress={() =>
                                              handleDisconnect(provider, conn)
                                            }
                                            className="p-2"
                                          >
                                            <Icon
                                              as={TrashIcon}
                                              size="sm"
                                            />
                                          </Pressable>
                                        </HStack>
                                      </HStack>
                                    )
                                  )}
                                </VStack>
                              )}
                            </Box>
                          </TableData>
                        </TableRow>
                      )}
                    </React.Fragment>
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
                label="API Key"
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

      <BaseModal
        visible={addModelTarget !== null}
        onClose={closeAddModel}
        maxWidth={420}
        cardStyle={{ padding: 0 }}
      >
        <ScrollView contentContainerStyle={{ padding: 24 }}>
          <Text className="mb-4 text-base font-bold text-black dark:text-white">
            Add Model to {addModelTarget?.name}
          </Text>
          <VStack space="md">
            <FieldLabel label="Model" />
            <ModelPicker
              models={allModels}
              selectedId={addModelId}
              onSelect={setAddModelId}
              excludedIds={(providerModels[addModelTarget?.id ?? -1] ?? []).map(
                (c) => String(c.model_id)
              )}
              placeholder="Select model..."
            />
            <EditField
              label="Endpoint (optional)"
              value={addModelEndpoint}
              onChangeText={setAddModelEndpoint}
              placeholder="https://..."
            />
            <EditField
              label="API Key (optional)"
              value={addModelApiKey}
              onChangeText={setAddModelApiKey}
              placeholder="sk-..."
            />
            {addModelMsg && (
              <Text
                className={`text-xs ${
                  addModelMsg === "Connected."
                    ? "text-green-500"
                    : "text-red-500"
                }`}
              >
                {addModelMsg}
              </Text>
            )}
            <HStack className="justify-end gap-2">
              <Button variant="outline" onPress={closeAddModel}>
                <ButtonText>Cancel</ButtonText>
              </Button>
              <Button
                onPress={handleAddModel}
                isDisabled={addModelSaving || !addModelId}
              >
                <ButtonText>
                  {addModelSaving ? "Connecting..." : "Connect"}
                </ButtonText>
              </Button>
            </HStack>
          </VStack>
        </ScrollView>
      </BaseModal>

      <BaseModal
        visible={editConn !== null}
        onClose={closeEditConn}
        maxWidth={420}
        cardStyle={{ padding: 0 }}
      >
        <ScrollView contentContainerStyle={{ padding: 24 }}>
          <Text className="mb-1 text-base font-bold text-black dark:text-white">
            Edit Connection
          </Text>
          <Text className="mb-4 text-xs text-gray-500">
            {editConn?.conn.model_name} → {editConn?.provider.name}
          </Text>
          <VStack space="md">
            <EditField
              label="Endpoint"
              value={editConnEndpoint}
              onChangeText={setEditConnEndpoint}
              placeholder="https://..."
            />
            <EditField
              label="API Key"
              value={editConnApiKey}
              onChangeText={setEditConnApiKey}
              placeholder="sk-..."
            />
            {editConnMsg && (
              <Text
                className={`text-xs ${
                  editConnMsg === "Saved." ? "text-green-500" : "text-red-500"
                }`}
              >
                {editConnMsg}
              </Text>
            )}
            <HStack className="justify-end gap-2">
              <Button variant="outline" onPress={closeEditConn}>
                <ButtonText>Cancel</ButtonText>
              </Button>
              <Button onPress={handleEditConn} isDisabled={editConnSaving}>
                <ButtonText>{editConnSaving ? "Saving..." : "Save"}</ButtonText>
              </Button>
            </HStack>
          </VStack>
        </ScrollView>
      </BaseModal>
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
