import React, { useState, useEffect } from "react";
import { View, Pressable, ScrollView } from "react-native";
import { BaseModal } from "./base-modal";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonText, ButtonSpinner } from "@/components/ui/button";
import { Box } from "@/components/ui/box";
import { Input, InputField } from "@/components/ui/input";
import { API_BASE } from "@/components/statistics/constants";
import { useAuth } from "@/components/auth-shell";
import { Icon, CheckIcon } from "@/components/ui/icon";

const MICRO_CENTS_PER_DOLLAR = 100000000;

const formatMicroCentsToDollars = (microCents: number | null | undefined) => {
  if (microCents == null || microCents < 0) return "";
  return (Number(microCents) / MICRO_CENTS_PER_DOLLAR).toString();
};

const parseDollarsToMicroCents = (dollarsStr: string) => {
  const cleaned = dollarsStr.trim().replace("$", "").replace(",", ".");

  if (!cleaned) return null;

  const parsed = Number(cleaned);

  if (!Number.isFinite(parsed) || parsed < 0) return null;

  return Math.round(parsed * MICRO_CENTS_PER_DOLLAR);
};

const formatBudget = (microCents: number | null | undefined) => {
  if (microCents == null || microCents < 0) return "∞";
  return `$${(microCents / MICRO_CENTS_PER_DOLLAR).toFixed(2)}`;
};

export function ApiKeyModal({
  visible,
  onClose,
  apiKeyData,
  team,
  canEdit = true,
  onSaved,
}: {
  visible: boolean;
  onClose: () => void;
  apiKeyData: any | null;
  team?: any;
  canEdit?: boolean;
  onSaved?: () => void;
}) {
  const { apiKey } = useAuth();

  const [environment, setEnvironment] = useState("");
  const [priority, setPriority] = useState("0");
  const [logLevel, setLogLevel] = useState<"BILLING" | "FULL">("BILLING");

  const [keyBudget, setKeyBudget] = useState("");
  const [cloudRpm, setCloudRpm] = useState("");
  const [cloudTpm, setCloudTpm] = useState("");
  const [localRpm, setLocalRpm] = useState("");
  const [localTpm, setLocalTpm] = useState("");

  const [allModels, setAllModels] = useState<any[]>([]);
  const [selectedModelIds, setSelectedModelIds] = useState<string[]>([]);
  const [teamModelIds, setTeamModelIds] = useState<string[]>([]);
  const [modelSearch, setModelSearch] = useState("");

  const [isSaving, setIsSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (apiKeyData && visible) {
      setEnvironment(apiKeyData.environment || "");
      setPriority(String(apiKeyData.default_priority || 0));
      setLogLevel(apiKeyData.log || "BILLING");

      const s = apiKeyData.settings || {};

      setKeyBudget(formatMicroCentsToDollars(s.budget_limit_micro_cents));

      setCloudRpm(
        s.cloud_rpm_limit && s.cloud_rpm_limit > 0
          ? String(s.cloud_rpm_limit)
          : ""
      );
      setCloudTpm(
        s.cloud_tpm_limit && s.cloud_tpm_limit > 0
          ? String(s.cloud_tpm_limit)
          : ""
      );
      setLocalRpm(
        s.local_rpm_limit && s.local_rpm_limit > 0
          ? String(s.local_rpm_limit)
          : ""
      );
      setLocalTpm(
        s.local_tpm_limit && s.local_tpm_limit > 0
          ? String(s.local_tpm_limit)
          : ""
      );

      fetchModels();
      fetchKeyPermissions();
      if (team?.id) fetchTeamPermissions();

      setCopied(false);
    }
  }, [apiKeyData, visible, team]);

  const fetchModels = async () => {
    try {
      const res = await fetch(`${API_BASE}/logosdb/get_models`, {
        method: "POST",
        headers: { "logos-key": apiKey, "Content-Type": "application/json" },
        body: JSON.stringify({ logos_key: apiKey }),
      });

      const data = await res.json();

      const formatted = data.map((m: any) => {
        if (Array.isArray(m)) return { id: m[0], name: m[1] };
        return { id: m.id, name: m.name };
      });

      setAllModels(formatted);
    } catch (e) {
      console.error("Error fetching models", e);
    }
  };

  const fetchKeyPermissions = async () => {
    try {
      const res = await fetch(
        `${API_BASE}/admin/api-keys/${apiKeyData.id}/model-permissions`,
        {
          headers: { "logos-key": apiKey },
        }
      );

      const ids = await res.json();
      setSelectedModelIds(ids.map(String));
    } catch (e) {
      console.error("Error fetching key perms", e);
    }
  };

  const fetchTeamPermissions = async () => {
    try {
      const res = await fetch(
        `${API_BASE}/admin/teams/${team.id}/model-permissions`,
        {
          headers: { "logos-key": apiKey },
        }
      );

      const ids = await res.json();
      setTeamModelIds(ids.map(String));
    } catch (e) {
      console.error("Error fetching team perms", e);
    }
  };

  const toggleModel = (id: number | string) => {
    const sId = String(id);

    setSelectedModelIds((prev) =>
      prev.includes(sId) ? prev.filter((x) => x !== sId) : [...prev, sId]
    );
  };

  if (!apiKeyData) return null;

  const maskedKey = apiKeyData.key_value
    ? `${apiKeyData.key_value.substring(0, 14)}••••••••••••••••`
    : "";

  const isDeveloperKey = apiKeyData.key_type === "developer";

  const teamDefBudget = team?.default_monthly_budget_micro_cents;
  const teamDefCloudRpm = team?.default_cloud_rpm_limit;
  const teamDefCloudTpm = team?.default_cloud_tpm_limit;
  const teamDefLocalRpm = team?.default_local_rpm_limit;
  const teamDefLocalTpm = team?.default_local_tpm_limit;

  const parsedKeyBudget = parseDollarsToMicroCents(keyBudget);

  const activeBudget =
    parsedKeyBudget !== null ? parsedKeyBudget : teamDefBudget;

  const activeCloudRpm = cloudRpm ? parseInt(cloudRpm, 10) : teamDefCloudRpm;
  const activeCloudTpm = cloudTpm ? parseInt(cloudTpm, 10) : teamDefCloudTpm;
  const activeLocalRpm = localRpm ? parseInt(localRpm, 10) : teamDefLocalRpm;
  const activeLocalTpm = localTpm ? parseInt(localTpm, 10) : teamDefLocalTpm;

  const usedBudget = apiKeyData.used_micro_cents || 0;

  const handleCopy = async () => {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(apiKeyData.key_value);
    }

    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSave = async () => {
    const parsedBudget = parseDollarsToMicroCents(keyBudget);

    if (keyBudget.trim() && parsedBudget === null) {
      alert("Please enter a valid budget amount in dollars.");
      return;
    }

    setIsSaving(true);

    try {
      const patchRes = await fetch(
        `${API_BASE}/admin/api-keys/${apiKeyData.id}`,
        {
          method: "PATCH",
          headers: { "logos-key": apiKey, "Content-Type": "application/json" },
          body: JSON.stringify({
            environment: isDeveloperKey ? "" : environment.trim() || "",
            default_priority: parseInt(priority, 10) || 0,
            log: logLevel,

            budget_limit_micro_cents: parsedBudget ?? -1,

            cloud_rpm_limit: cloudRpm.trim() ? parseInt(cloudRpm, 10) : -1,
            cloud_tpm_limit: cloudTpm.trim() ? parseInt(cloudTpm, 10) : -1,
            local_rpm_limit: localRpm.trim() ? parseInt(localRpm, 10) : -1,
            local_tpm_limit: localTpm.trim() ? parseInt(localTpm, 10) : -1,
          }),
        }
      );

      if (!patchRes.ok) {
        const err = await patchRes.json().catch(() => null);
        alert(err?.detail || "Failed to save API Key settings.");
        return;
      }

      const permsRes = await fetch(
        `${API_BASE}/admin/api-keys/${apiKeyData.id}/model-permissions`,
        {
          method: "PUT",
          headers: { "logos-key": apiKey, "Content-Type": "application/json" },
          body: JSON.stringify({ model_ids: selectedModelIds.map(Number) }),
        }
      );

      if (!permsRes.ok) {
        const err = await permsRes.json().catch(() => null);
        alert(err?.detail || "Failed to save model permissions.");
        return;
      }

      if (onSaved) onSaved();
      onClose();
    } catch (e) {
      alert("Network error: Failed to save API Key configuration.");
    } finally {
      setIsSaving(false);
    }
  };

  const filteredModels = allModels.filter((m) => {
    const modelName = m?.name || "";
    const searchTerm = modelSearch || "";

    return modelName.toLowerCase().includes(searchTerm.toLowerCase());
  });

  return (
    <BaseModal visible={visible} onClose={onClose} maxWidth={650}>
      <VStack space="lg" style={{ flexShrink: 1, maxHeight: "90vh" as any }}>
        <Text className="text-xl font-bold text-typography-900">
          {isDeveloperKey ? "Developer Key Settings" : "Service Key Settings"}
        </Text>

        <ScrollView
          showsVerticalScrollIndicator={true}
          style={{ flexShrink: 1 }}
        >
          <VStack space="xl" style={{ paddingBottom: 20 }}>
            <VStack space="md">
              <Text className="text-sm font-bold text-typography-800">
                Usage Limits & Settings
              </Text>

              <Box className="rounded-lg border border-outline-200 bg-secondary-50 p-3">
                <HStack className="items-center justify-between">
                  <VStack>
                    <Text className="mb-1 text-xs font-semibold text-typography-500">
                      SECRET KEY
                    </Text>

                    <Text
                      className="text-sm font-medium text-typography-900"
                      style={{ fontFamily: "monospace" }}
                    >
                      {maskedKey}
                    </Text>
                  </VStack>

                  <Button
                    variant="outline"
                    size="sm"
                    onPress={handleCopy}
                    className={
                      copied ? "border-success-500" : "border-outline-300"
                    }
                  >
                    <ButtonText className={copied ? "text-success-500" : ""}>
                      {copied ? "Copied!" : "Copy"}
                    </ButtonText>
                  </Button>
                </HStack>
              </Box>

              <HStack space="md">
                <Box
                  style={{
                    flex: 1,
                    backgroundColor: "#fff",
                    padding: 12,
                    borderRadius: 8,
                    borderWidth: 1,
                    borderColor: "#e2e8f0",
                  }}
                >
                  <Text
                    style={{
                      fontSize: 11,
                      color: "#6b7280",
                      fontWeight: "600",
                    }}
                  >
                    Budget Usage
                  </Text>

                  <Text
                    style={{
                      fontSize: 16,
                      fontWeight: "700",
                      color: "#111827",
                      marginTop: 4,
                    }}
                  >
                    {formatBudget(usedBudget)}{" "}
                    <Text
                      style={{
                        fontSize: 12,
                        color: "#6b7280",
                        fontWeight: "400",
                      }}
                    >
                      / {formatBudget(activeBudget)}
                    </Text>
                  </Text>

                  <Text
                    style={{ fontSize: 10, color: "#9ca3af", marginTop: 2 }}
                  >
                    {parsedKeyBudget !== null ? "Custom Limit" : "Team Default"}
                  </Text>
                </Box>

                <Box
                  style={{
                    flex: 1.1,
                    backgroundColor: "#fff",
                    padding: 12,
                    borderRadius: 8,
                    borderWidth: 1,
                    borderColor: "#e2e8f0",
                  }}
                >
                  <Text
                    style={{
                      fontSize: 11,
                      color: "#6b7280",
                      fontWeight: "600",
                    }}
                  >
                    Cloud Limits
                  </Text>

                  <HStack
                    space="md"
                    style={{ marginTop: 4, alignItems: "flex-end" }}
                  >
                    <VStack>
                      <Text
                        style={{
                          fontSize: 16,
                          fontWeight: "700",
                          color: "#111827",
                        }}
                      >
                        {activeCloudRpm || "∞"}
                      </Text>

                      <Text
                        style={{
                          fontSize: 10,
                          color: "#6b7280",
                          fontWeight: "500",
                        }}
                      >
                        RPM
                      </Text>
                    </VStack>

                    <View
                      style={{
                        width: 1,
                        height: 24,
                        backgroundColor: "#e2e8f0",
                        marginBottom: 2,
                      }}
                    />

                    <VStack>
                      <Text
                        style={{
                          fontSize: 16,
                          fontWeight: "700",
                          color: "#111827",
                        }}
                      >
                        {activeCloudTpm || "∞"}
                      </Text>

                      <Text
                        style={{
                          fontSize: 10,
                          color: "#6b7280",
                          fontWeight: "500",
                        }}
                      >
                        TPM
                      </Text>
                    </VStack>
                  </HStack>
                </Box>

                <Box
                  style={{
                    flex: 1.1,
                    backgroundColor: "#fff",
                    padding: 12,
                    borderRadius: 8,
                    borderWidth: 1,
                    borderColor: "#e2e8f0",
                  }}
                >
                  <Text
                    style={{
                      fontSize: 11,
                      color: "#6b7280",
                      fontWeight: "600",
                    }}
                  >
                    Local Limits
                  </Text>

                  <HStack
                    space="md"
                    style={{ marginTop: 4, alignItems: "flex-end" }}
                  >
                    <VStack>
                      <Text
                        style={{
                          fontSize: 16,
                          fontWeight: "700",
                          color: "#111827",
                        }}
                      >
                        {activeLocalRpm || "∞"}
                      </Text>

                      <Text
                        style={{
                          fontSize: 10,
                          color: "#6b7280",
                          fontWeight: "500",
                        }}
                      >
                        RPM
                      </Text>
                    </VStack>

                    <View
                      style={{
                        width: 1,
                        height: 24,
                        backgroundColor: "#e2e8f0",
                        marginBottom: 2,
                      }}
                    />

                    <VStack>
                      <Text
                        style={{
                          fontSize: 16,
                          fontWeight: "700",
                          color: "#111827",
                        }}
                      >
                        {activeLocalTpm || "∞"}
                      </Text>

                      <Text
                        style={{
                          fontSize: 10,
                          color: "#6b7280",
                          fontWeight: "500",
                        }}
                      >
                        TPM
                      </Text>
                    </VStack>
                  </HStack>
                </Box>
              </HStack>
            </VStack>

            {canEdit && <View className="my-1 h-px w-full bg-outline-200" />}

            {canEdit && (
              <VStack space="md">
                <Text
                  style={{ fontWeight: "700", fontSize: 14, color: "#374151" }}
                >
                  Override Key Settings
                </Text>

                <VStack space="xs">
                  <Text
                    style={{ fontSize: 12, fontWeight: "600", color: "#555" }}
                  >
                    Specific Budget Limit ($)
                  </Text>

                  <Input
                    variant="outline"
                    size="md"
                    isDisabled={!canEdit}
                    style={{ backgroundColor: "#fff" }}
                  >
                    <InputField
                      value={keyBudget}
                      onChangeText={setKeyBudget}
                      keyboardType="decimal-pad"
                      placeholder="e.g. 150.50 (leave empty for Team Default)"
                    />
                  </Input>
                </VStack>

                <HStack space="md">
                  <VStack space="xs" style={{ flex: 1 }}>
                    <Text
                      style={{ fontSize: 12, fontWeight: "600", color: "#555" }}
                    >
                      Cloud RPM
                    </Text>

                    <Input
                      variant="outline"
                      size="md"
                      isDisabled={!canEdit}
                      style={{ backgroundColor: "#fff" }}
                    >
                      <InputField
                        value={cloudRpm}
                        onChangeText={setCloudRpm}
                        keyboardType="numeric"
                        placeholder="Team Default"
                      />
                    </Input>
                  </VStack>

                  <VStack space="xs" style={{ flex: 1 }}>
                    <Text
                      style={{ fontSize: 12, fontWeight: "600", color: "#555" }}
                    >
                      Cloud TPM
                    </Text>

                    <Input
                      variant="outline"
                      size="md"
                      isDisabled={!canEdit}
                      style={{ backgroundColor: "#fff" }}
                    >
                      <InputField
                        value={cloudTpm}
                        onChangeText={setCloudTpm}
                        keyboardType="numeric"
                        placeholder="Team Default"
                      />
                    </Input>
                  </VStack>
                </HStack>

                <HStack space="md">
                  <VStack space="xs" style={{ flex: 1 }}>
                    <Text
                      style={{ fontSize: 12, fontWeight: "600", color: "#555" }}
                    >
                      Local RPM
                    </Text>

                    <Input
                      variant="outline"
                      size="md"
                      isDisabled={!canEdit}
                      style={{ backgroundColor: "#fff" }}
                    >
                      <InputField
                        value={localRpm}
                        onChangeText={setLocalRpm}
                        keyboardType="numeric"
                        placeholder="Team Default"
                      />
                    </Input>
                  </VStack>

                  <VStack space="xs" style={{ flex: 1 }}>
                    <Text
                      style={{ fontSize: 12, fontWeight: "600", color: "#555" }}
                    >
                      Local TPM
                    </Text>

                    <Input
                      variant="outline"
                      size="md"
                      isDisabled={!canEdit}
                      style={{ backgroundColor: "#fff" }}
                    >
                      <InputField
                        value={localTpm}
                        onChangeText={setLocalTpm}
                        keyboardType="numeric"
                        placeholder="Team Default"
                      />
                    </Input>
                  </VStack>
                </HStack>

                <HStack space="md">
                  {!isDeveloperKey && (
                    <VStack space="xs" style={{ flex: 1 }}>
                      <Text
                        style={{
                          fontSize: 12,
                          fontWeight: "600",
                          color: "#555",
                        }}
                      >
                        Environment
                      </Text>

                      <Input
                        variant="outline"
                        size="md"
                        isDisabled={!canEdit}
                        style={{ backgroundColor: "#fff" }}
                      >
                        <InputField
                          value={environment}
                          onChangeText={setEnvironment}
                          placeholder="prod, dev..."
                        />
                      </Input>
                    </VStack>
                  )}

                  <VStack space="xs" style={{ flex: 1 }}>
                    <Text
                      style={{ fontSize: 12, fontWeight: "600", color: "#555" }}
                    >
                      Queue Priority
                    </Text>

                    <Input
                      variant="outline"
                      size="md"
                      isDisabled={!canEdit}
                      style={{ backgroundColor: "#fff" }}
                    >
                      <InputField
                        value={priority}
                        onChangeText={setPriority}
                        keyboardType="numeric"
                      />
                    </Input>
                  </VStack>
                </HStack>
              </VStack>
            )}

            {canEdit && <View className="my-1 h-px w-full bg-outline-200" />}

            {canEdit && (
              <VStack space="md">
                <VStack space="xs">
                  <Text className="text-sm font-bold text-typography-800">
                    Model Access
                  </Text>

                  <Text className="text-xs text-typography-500">
                    Models from the team are always available. You can add
                    specific models for this key.
                  </Text>
                </VStack>

                <Input
                  variant="outline"
                  size="sm"
                  style={{ backgroundColor: "#fff" }}
                >
                  <InputField
                    placeholder="Search models..."
                    value={modelSearch}
                    onChangeText={setModelSearch}
                  />
                </Input>

                <Box
                  className="rounded-lg border border-outline-200 bg-background-0"
                  style={{ maxHeight: 250 }}
                >
                  <ScrollView nestedScrollEnabled={true}>
                    <VStack space="xs" style={{ paddingVertical: 4 }}>
                      {filteredModels.map((model) => {
                        const isTeamModel = teamModelIds.includes(
                          String(model.id)
                        );

                        const isKeySpecific = selectedModelIds.includes(
                          String(model.id)
                        );

                        const isSelected = isTeamModel || isKeySpecific;

                        return (
                          <Pressable
                            key={model.id}
                            onPress={() => {
                              if (canEdit && !isTeamModel) {
                                toggleModel(model.id);
                              }
                            }}
                            style={{
                              paddingHorizontal: 12,
                              paddingVertical: 10,
                              borderBottomWidth: 1,
                              borderBottomColor: "#f3f4f6",
                              flexDirection: "row",
                              alignItems: "center",
                              opacity: isTeamModel ? 0.6 : 1,
                            }}
                          >
                            <View
                              style={{
                                width: 20,
                                height: 20,
                                borderRadius: 4,
                                borderWidth: 1,
                                alignItems: "center",
                                justifyContent: "center",
                                marginRight: 14,
                                borderColor: isTeamModel
                                  ? "#9ca3af"
                                  : isKeySpecific
                                    ? "#006DFF"
                                    : "#cbd5e1",
                                backgroundColor: isTeamModel
                                  ? "#9ca3af"
                                  : isKeySpecific
                                    ? "#006DFF"
                                    : "transparent",
                              }}
                            >
                              {isSelected && (
                                <Icon as={CheckIcon} size="xs" color="white" />
                              )}
                            </View>

                            <Text
                              style={{
                                fontWeight: "600",
                                fontSize: 14,
                                color: "#111827",
                              }}
                            >
                              {model.name}
                            </Text>
                          </Pressable>
                        );
                      })}

                      {filteredModels.length === 0 && (
                        <Text className="mt-4 text-center text-xs text-typography-400">
                          No models found.
                        </Text>
                      )}
                    </VStack>
                  </ScrollView>
                </Box>
              </VStack>
            )}
          </VStack>
        </ScrollView>

        <HStack
          space="md"
          className="justify-end border-t border-outline-200 pt-4"
        >
          <Button variant="outline" onPress={onClose}>
            <ButtonText>{canEdit ? "Cancel" : "Close"}</ButtonText>
          </Button>

          {canEdit && (
            <Button
              onPress={handleSave}
              disabled={isSaving}
              className="min-w-[100px]"
            >
              {isSaving && <ButtonSpinner color="white" />}
              <ButtonText>{isSaving ? "Saving..." : "Save Changes"}</ButtonText>
            </Button>
          )}
        </HStack>
      </VStack>
    </BaseModal>
  );
}
