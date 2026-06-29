import React, { useState, useEffect } from "react";
import { View, Pressable, ScrollView, Switch } from "react-native";
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
  const { apiKey, role } = useAuth();
  const isLogosAdmin = role === "logos_admin";

  const [environment, setEnvironment] = useState("");
  const [priority, setPriority] = useState("0");
  const [logLevel, setLogLevel] = useState<"BILLING" | "FULL">("BILLING");
  const [useCustomPerms, setUseCustomPerms] = useState(false);

  const [keyBudget, setKeyBudget] = useState("");
  const [cloudRpm, setCloudRpm] = useState("");
  const [cloudTpm, setCloudTpm] = useState("");
  const [localRpm, setLocalRpm] = useState("");
  const [localTpm, setLocalTpm] = useState("");

  const [allModels, setAllModels] = useState<any[]>([]);
  const [allProviders, setAllProviders] = useState<any[]>([]);
  const [providerModelMap, setProviderModelMap] = useState<
    Record<string, string[]>
  >({});

  const [selectedModelIds, setSelectedModelIds] = useState<string[]>([]);
  const [teamModelIds, setTeamModelIds] = useState<string[]>([]);

  const [selectedProviderIds, setSelectedProviderIds] = useState<string[]>([]);
  const [teamProviderIds, setTeamProviderIds] = useState<string[]>([]);

  const [modelSearch, setModelSearch] = useState("");
  const [providerSearch, setProviderSearch] = useState("");

  const [isSaving, setIsSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (apiKeyData && visible) {
      setEnvironment(apiKeyData.environment || "");
      setPriority(String(apiKeyData.default_priority || 0));
      setLogLevel(apiKeyData.log || "BILLING");
      setUseCustomPerms(!!apiKeyData.use_custom_permissions);

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

      fetchInitialData();
      setCopied(false);
    }
  }, [apiKeyData, visible, team]);

  const fetchInitialData = async () => {
    try {
      const modelRes = await fetch(`${API_BASE}/logosdb/get_models`, {
        method: "POST",
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ logos_key: apiKey }),
      });
      const modelData = await modelRes.json();
      setAllModels(
        modelData.map((m: any) => ({ id: m.id || m[0], name: m.name || m[1] }))
      );

      const providerRes = await fetch(`${API_BASE}/logosdb/get_providers`, {
        method: "POST",
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({ logos_key: apiKey }),
      });
      const providerData = await providerRes.json();
      setAllProviders(providerData);

      const map: Record<string, string[]> = {};
      for (const p of providerData) {
        const providerModelsRes = await fetch(`${API_BASE}/logosdb/get_provider_models`, {
          method: "POST",
          headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
          body: JSON.stringify({ logos_key: apiKey, provider_id: p.id }),
        });
        const providerModelsData = await providerModelsRes.json();
        map[String(p.id)] = providerModelsData.map((m: any) => String(m.model_id));
      }
      setProviderModelMap(map);

      const apiKeyProviderPermissionsRes = await fetch(
        `${API_BASE}/admin/api-keys/${apiKeyData.id}/provider-permissions`,
        { headers: { Authorization: `Bearer ${apiKey}` } }
      );
      setSelectedProviderIds((await apiKeyProviderPermissionsRes.json()).map(String));

      const apiKeyModelPermissionsRes = await fetch(
        `${API_BASE}/admin/api-keys/${apiKeyData.id}/model-permissions`,
        { headers: { Authorization: `Bearer ${apiKey}` } }
      );
      setSelectedModelIds((await apiKeyModelPermissionsRes.json()).map(String));

      if (team?.id) {
        const teamProviderPermissionsRes = await fetch(
          `${API_BASE}/admin/teams/${team.id}/provider-permissions`,
          { headers: { Authorization: `Bearer ${apiKey}` } }
        );
        setTeamProviderIds((await teamProviderPermissionsRes.json()).map(String));

        const teamModelPermissionsRes = await fetch(
          `${API_BASE}/admin/teams/${team.id}/model-permissions`,
          { headers: { Authorization: `Bearer ${apiKey}` } }
        );
        setTeamModelIds((await teamModelPermissionsRes.json()).map(String));
      }
    } catch (e) {
      console.error("Error fetching modal initial data", e);
    }
  };

  const toggleModel = (id: number | string) => {
    const sId = String(id);

    setSelectedModelIds((prev) =>
      prev.includes(sId) ? prev.filter((x) => x !== sId) : [...prev, sId]
    );
  };

  const toggleProvider = (providerId: number | string) => {
    const providerIdString = String(providerId);

    setSelectedProviderIds((currentSelectedIds) =>
      currentSelectedIds.includes(providerIdString)
        ? currentSelectedIds.filter(
            (existingId) => existingId !== providerIdString
          )
        : [...currentSelectedIds, providerIdString]
    );
  };

  if (!apiKeyData) return null;

  const maskedKey = apiKeyData.key_value
    ? `${apiKeyData.key_value.substring(0, 14)}••••••••••••••••`
    : "";

  const isDeveloperKey = apiKeyData.key_type === "developer";
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
          headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
          body: JSON.stringify({
            environment: isDeveloperKey ? "" : environment.trim() || "",
            default_priority: parseInt(priority, 10) || 0,
            log: logLevel,
            use_custom_permissions: useCustomPerms,
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

      if (useCustomPerms) {
        if (isLogosAdmin) {
          await fetch(
            `${API_BASE}/admin/api-keys/${apiKeyData.id}/provider-permissions`,
            {
              method: "PUT",
              headers: {
                Authorization: `Bearer ${apiKey}`,
                "Content-Type": "application/json",
              },
              body: JSON.stringify({
                provider_ids: selectedProviderIds.map(Number),
              }),
            }
          );
        }

        await fetch(
          `${API_BASE}/admin/api-keys/${apiKeyData.id}/model-permissions`,
          {
            method: "PUT",
            headers: {
              Authorization: `Bearer ${apiKey}`,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ model_ids: selectedModelIds.map(Number) }),
          }
        );
      }

      if (onSaved) onSaved();
      onClose();
    } catch (e) {
      alert("Network error: Failed to save API Key configuration.");
    } finally {
      setIsSaving(false);
    }
  };

  const activeProviderIds = useCustomPerms
    ? selectedProviderIds
    : teamProviderIds;
  const allowedModelIds = new Set<string>();
  for (const pid of activeProviderIds) {
    const mids = providerModelMap[pid] || [];
    mids.forEach((m) => allowedModelIds.add(m));
  }

  const displayModels = allModels.filter(
    (m) =>
      allowedModelIds.has(String(m.id)) &&
      m.name.toLowerCase().includes(modelSearch.toLowerCase())
  );
  const displayProviders = allProviders.filter((p) =>
    p.name.toLowerCase().includes(providerSearch.toLowerCase())
  );

  return (
    <BaseModal visible={visible} onClose={onClose} maxWidth={800}>
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
                    <Text style={{ fontSize: 12, color: "#6b7280" }}>
                      /{" "}
                      {formatBudget(
                        parseDollarsToMicroCents(keyBudget) ??
                          team?.default_monthly_budget_micro_cents
                      )}
                    </Text>
                  </Text>

                  <Text
                    style={{ fontSize: 10, color: "#9ca3af", marginTop: 2 }}
                  >
                    {parseDollarsToMicroCents(keyBudget) !== null
                      ? "Custom Limit"
                      : "Team Default"}
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
                      <Text style={{ fontSize: 16, fontWeight: "700" }}>
                        {cloudRpm || team?.default_cloud_rpm_limit || "∞"}
                      </Text>
                      <Text style={{ fontSize: 10, color: "#6b7280" }}>
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
                      <Text style={{ fontSize: 16, fontWeight: "700" }}>
                        {cloudTpm || team?.default_cloud_tpm_limit || "∞"}
                      </Text>
                      <Text style={{ fontSize: 10, color: "#6b7280" }}>
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
                      <Text style={{ fontSize: 16, fontWeight: "700" }}>
                        {localRpm || team?.default_local_rpm_limit || "∞"}
                      </Text>
                      <Text style={{ fontSize: 10, color: "#6b7280" }}>
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
                      <Text style={{ fontSize: 16, fontWeight: "700" }}>
                        {localTpm || team?.default_local_tpm_limit || "∞"}
                      </Text>
                      <Text style={{ fontSize: 10, color: "#6b7280" }}>
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
                <HStack
                  style={{
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <VStack space="xs" style={{ flex: 1, paddingRight: 16 }}>
                    <Text
                      style={{
                        fontWeight: "700",
                        fontSize: 14,
                        color: "#111827",
                      }}
                    >
                      Override Team Infrastructure Rules
                    </Text>
                    <Text style={{ fontSize: 12, color: "#6b7280" }}>
                      If enabled, this API key ignores Team rules entirely and
                      uses custom permissions.{" "}
                      {!isLogosAdmin && "(Logos Admin only)"}
                    </Text>
                  </VStack>

                  <Pressable
                    onPress={() =>
                      isLogosAdmin && setUseCustomPerms(!useCustomPerms)
                    }
                    disabled={!isLogosAdmin}
                    style={
                      {
                        width: 44,
                        height: 24,
                        borderRadius: 12,
                        backgroundColor: useCustomPerms ? "#006DFF" : "#e2e8f0",
                        justifyContent: "center",
                        padding: 2,

                        opacity: isLogosAdmin ? 1 : 0.5,
                        outlineStyle: "none",
                      } as any
                    }
                  >
                    <View
                      style={{
                        width: 20,
                        height: 20,
                        borderRadius: 10,
                        backgroundColor: "#ffffff",
                        transform: [{ translateX: useCustomPerms ? 20 : 0 }],
                        shadowColor: "#000",
                        shadowOffset: { width: 0, height: 2 },
                        shadowOpacity: 0.2,
                        shadowRadius: 2,
                        elevation: 2,
                      }}
                    />
                  </Pressable>
                </HStack>

                {!useCustomPerms ? (
                  <Text
                    style={{ fontSize: 13, color: "#6b7280", marginTop: 4 }}
                  >
                    Inheriting {teamProviderIds.length} Providers and{" "}
                    {teamModelIds.length} Models from Team.
                  </Text>
                ) : (
                  <HStack space="xl" style={{ marginTop: 8 }}>
                    {isLogosAdmin && (
                      <VStack style={{ flex: 1 }} space="sm">
                        <Text
                          style={{
                            fontSize: 13,
                            fontWeight: "600",
                            color: "#374151",
                          }}
                        >
                          Allowed Providers
                        </Text>
                        <Input
                          variant="outline"
                          size="sm"
                          style={{ backgroundColor: "#ffffff" }}
                        >
                          <InputField
                            placeholder="Search providers..."
                            value={providerSearch}
                            onChangeText={setProviderSearch}
                          />
                        </Input>
                        <Box
                          className="rounded-lg border border-outline-200"
                          style={{ height: 260, backgroundColor: "#ffffff" }}
                        >
                          <ScrollView nestedScrollEnabled={true}>
                            <VStack style={{ paddingVertical: 4 }}>
                              {displayProviders.map((p) => {
                                const isSelected = selectedProviderIds.includes(
                                  String(p.id)
                                );
                                return (
                                  <Pressable
                                    key={p.id}
                                    onPress={() => toggleProvider(p.id)}
                                    style={{
                                      paddingHorizontal: 12,
                                      paddingVertical: 10,
                                      borderBottomWidth: 1,
                                      borderBottomColor: "#f3f4f6",
                                      flexDirection: "row",
                                      alignItems: "center",
                                    }}
                                  >
                                    <View
                                      style={{
                                        width: 18,
                                        height: 18,
                                        borderRadius: 4,
                                        borderWidth: 1,
                                        alignItems: "center",
                                        justifyContent: "center",
                                        marginRight: 12,
                                        borderColor: isSelected
                                          ? "#006DFF"
                                          : "#cbd5e1",
                                        backgroundColor: isSelected
                                          ? "#006DFF"
                                          : "transparent",
                                      }}
                                    >
                                      {isSelected && (
                                        <Icon
                                          as={CheckIcon}
                                          size="xs"
                                          color="white"
                                        />
                                      )}
                                    </View>
                                    <Text
                                      style={{
                                        fontWeight: "600",
                                        fontSize: 13,
                                        color: "#111827",
                                        flex: 1,
                                      }}
                                      numberOfLines={1}
                                    >
                                      {p.name}
                                    </Text>
                                  </Pressable>
                                );
                              })}
                              {displayProviders.length === 0 && (
                                <Text
                                  style={{
                                    marginTop: 16,
                                    textAlign: "center",
                                    fontSize: 12,
                                    color: "#9ca3af",
                                  }}
                                >
                                  No providers found.
                                </Text>
                              )}
                            </VStack>
                          </ScrollView>
                        </Box>
                      </VStack>
                    )}

                    <VStack style={{ flex: 1 }} space="sm">
                      <Text
                        style={{
                          fontSize: 13,
                          fontWeight: "600",
                          color: "#374151",
                        }}
                      >
                        Allowed Models
                      </Text>
                      <Input
                        variant="outline"
                        size="sm"
                        style={{ backgroundColor: "#ffffff" }}
                      >
                        <InputField
                          placeholder="Search models..."
                          value={modelSearch}
                          onChangeText={setModelSearch}
                        />
                      </Input>
                      <Box
                        className="rounded-lg border border-outline-200"
                        style={{ height: 260, backgroundColor: "#ffffff" }}
                      >
                        <ScrollView nestedScrollEnabled={true}>
                          <VStack style={{ paddingVertical: 4 }}>
                            {displayModels.map((model) => {
                              const isSelected = selectedModelIds.includes(
                                String(model.id)
                              );
                              return (
                                <Pressable
                                  key={model.id}
                                  onPress={() => toggleModel(model.id)}
                                  style={{
                                    paddingHorizontal: 12,
                                    paddingVertical: 10,
                                    borderBottomWidth: 1,
                                    borderBottomColor: "#f3f4f6",
                                    flexDirection: "row",
                                    alignItems: "center",
                                  }}
                                >
                                  <View
                                    style={{
                                      width: 18,
                                      height: 18,
                                      borderRadius: 4,
                                      borderWidth: 1,
                                      alignItems: "center",
                                      justifyContent: "center",
                                      marginRight: 12,
                                      borderColor: isSelected
                                        ? "#006DFF"
                                        : "#cbd5e1",
                                      backgroundColor: isSelected
                                        ? "#006DFF"
                                        : "transparent",
                                    }}
                                  >
                                    {isSelected && (
                                      <Icon
                                        as={CheckIcon}
                                        size="xs"
                                        color="white"
                                      />
                                    )}
                                  </View>
                                  <Text
                                    style={{
                                      fontWeight: "600",
                                      fontSize: 13,
                                      color: "#111827",
                                      flex: 1,
                                    }}
                                    numberOfLines={1}
                                  >
                                    {model.name}
                                  </Text>
                                </Pressable>
                              );
                            })}
                            {displayModels.length === 0 && (
                              <Text
                                style={{
                                  marginTop: 16,
                                  textAlign: "center",
                                  fontSize: 12,
                                  color: "#9ca3af",
                                }}
                              >
                                No supported models.
                              </Text>
                            )}
                          </VStack>
                        </ScrollView>
                      </Box>
                    </VStack>
                  </HStack>
                )}
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
