import React, { useState } from "react";
import { Pressable, ScrollView, View, ActivityIndicator } from "react-native";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Text } from "@/components/ui/text";
import { Button, ButtonText } from "@/components/ui/button";
import { Box } from "@/components/ui/box";
import { Input, InputField } from "@/components/ui/input";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableData,
} from "@/components/ui/table";
import { Icon, TrashIcon, EditIcon } from "@/components/ui/icon";
import { ApiKeyModal } from "@/components/modals/api-key-modal";
import { BaseModal } from "@/components/modals/base-modal";
import { ConfirmDeleteModal } from "@/components/modals/confirm-delete-modal";
import { API_BASE } from "@/components/statistics/constants";

const formatMicroCentsToDollars = (microCents: number | null | undefined) => {
  if (microCents == null) return "";
  return (Number(microCents) / 100000000).toString();
};

const parseDollarsToMicroCents = (dollarsStr: string) => {
  const cleaned = dollarsStr.trim().replace(",", ".");
  if (!cleaned) return null;
  const parsed = parseFloat(cleaned);
  if (isNaN(parsed)) return null;
  return Math.round(parsed * 100000000);
};

const colStyles: Record<string, any> = {
  keyName: { width: "15%", minWidth: 120 },
  env: { width: "15%", minWidth: 80 },
  budget: { width: "15%", minWidth: 100 },
  cloud: { width: "20%", minWidth: 140 },
  local: { width: "20%", minWidth: 140 },
  priority: { width: "8%", minWidth: 50 },
  actions: { width: 80, alignItems: "flex-end" },
};

export function Application_keys_tab({
  team,
  teamId,
  apiKeys,
  canEdit,
  canEditKeySettings,
  onRefresh,
  apiKey,
}: any) {
  const [selectedKey, setSelectedKey] = useState<any | null>(null);
  const [createVisible, setCreateVisible] = useState(false);
  const [deleteConfig, setDeleteConfig] = useState<{
    id: number;
    title: string;
    message: string;
  } | null>(null);

  const [newKeyEnv, setNewKeyEnv] = useState("prod");
  const [newKeyBudget, setNewKeyBudget] = useState("");
  const [newKeyCloudRpm, setNewKeyCloudRpm] = useState("");
  const [newKeyCloudTpm, setNewKeyCloudTpm] = useState("");
  const [newKeyLocalRpm, setNewKeyLocalRpm] = useState("");
  const [newKeyLocalTpm, setNewKeyLocalTpm] = useState("");
  const [newKeyPrio, setNewKeyPrio] = useState("0");
  const [isSaving, setIsSaving] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const resetCreateForm = () => {
    setNewKeyEnv("prod");
    setNewKeyBudget("");
    setNewKeyCloudRpm("");
    setNewKeyCloudTpm("");
    setNewKeyLocalRpm("");
    setNewKeyLocalTpm("");
    setNewKeyPrio("0");
    setCreateError(null);
  };

  const handleCreateKey = async () => {
    setIsSaving(true);
    try {
      const res = await fetch(`${API_BASE}/admin/teams/${teamId}/api-keys`, {
        method: "POST",
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `${team?.name || "team"}-${newKeyEnv}`,
          key_type: "application",
          environment: newKeyEnv.trim() || "",
          default_priority: parseInt(newKeyPrio, 10) || 0,
          log: "BILLING",
          settings: {
            budget_limit_micro_cents: parseDollarsToMicroCents(newKeyBudget),
            cloud_rpm_limit: newKeyCloudRpm.trim()
              ? parseInt(newKeyCloudRpm, 10)
              : null,
            cloud_tpm_limit: newKeyCloudTpm.trim()
              ? parseInt(newKeyCloudTpm, 10)
              : null,
            local_rpm_limit: newKeyLocalRpm.trim()
              ? parseInt(newKeyLocalRpm, 10)
              : null,
            local_tpm_limit: newKeyLocalTpm.trim()
              ? parseInt(newKeyLocalTpm, 10)
              : null,
          },
        }),
      });
      if (res.ok) {
        setCreateVisible(false);
        resetCreateForm();
        onRefresh();
      } else {
        let backendMsg = "Failed to create Application Key.";
        try {
          const errData = JSON.parse(await res.text());
          const raw = errData?.message || errData?.detail || errData?.error;
          if (typeof raw === "string") backendMsg = raw;
        } catch {}
        setCreateError(backendMsg);
      }
    } catch {
      setCreateError("Network error: Failed to create Application Key.");
    } finally {
      setIsSaving(false);
    }
  };

  const confirmDelete = async () => {
    if (!deleteConfig) return;
    try {
      const res = await fetch(`${API_BASE}/admin/api-keys/${deleteConfig.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${apiKey}` },
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        alert(err?.detail || "Failed to delete key.");
        return;
      }
      setDeleteConfig(null);
      onRefresh();
    } catch {
      alert("Network error: Failed to delete key.");
    }
  };

  const formatLimitNumber = (val: any, defaultVal: any) => {
    const effective = val !== null && val !== undefined ? val : defaultVal;
    if (effective === null || effective === undefined) return "∞";
    return effective >= 1000
      ? `${(effective / 1000).toFixed(0)}k`
      : String(effective);
  };

  const formatLimitBudget = (val: any, defaultVal: any) => {
    const effective = val !== null && val !== undefined ? val : defaultVal;
    if (effective === null || effective === undefined) return "∞";
    return `$${(effective / 100000000).toFixed(2)}`;
  };

  return (
    <VStack space="md" style={{ marginTop: 16, paddingBottom: 40 }}>
      <HStack
        style={{
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <Text style={{ fontWeight: "700", fontSize: 18 }}>
          Application Keys
        </Text>
        {canEdit && (
          <Button size="sm" onPress={() => setCreateVisible(true)}>
            <ButtonText>+ New Application Key</ButtonText>
          </Button>
        )}
      </HStack>

      {apiKeys.length === 0 ? (
        <Text style={{ color: "#9ca3af", fontSize: 13, marginTop: 16 }}>
          No Application Keys configured yet.
        </Text>
      ) : (
        <Box className="w-full overflow-hidden rounded-lg border border-outline-200 bg-secondary-200 p-2">
          <ScrollView horizontal contentContainerStyle={{ flexGrow: 1 }}>
            <Box className="min-w-full">
              <Table className="w-full">
                <TableHeader>
                  <TableRow className="bg-secondary-200">
                    <TableHead style={colStyles.keyName}>Label</TableHead>
                    <TableHead style={colStyles.env}>Env</TableHead>
                    <TableHead style={colStyles.budget}>Budget</TableHead>
                    <TableHead style={colStyles.cloud}>Cloud Limits</TableHead>
                    <TableHead style={colStyles.local}>Local Limits</TableHead>
                    <TableHead style={colStyles.priority}>Prio</TableHead>
                    <TableHead style={colStyles.actions}>{""}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {apiKeys.map((key: any) => {
                    const s = key.settings || {};
                    return (
                      <TableRow key={key.id} className="bg-secondary-200">
                        <TableData style={colStyles.keyName}>
                          <Text style={{ fontWeight: "600", fontSize: 13 }}>
                            {key.name}
                          </Text>
                        </TableData>
                        <TableData style={colStyles.env}>
                          <Text style={{ fontSize: 13, color: "#4b5563" }}>
                            {key.environment || "-"}
                          </Text>
                        </TableData>
                        <TableData style={colStyles.budget}>
                          <Text style={{ fontSize: 12, color: "#4b5563" }}>
                            {formatLimitBudget(
                              s.budget_limit_micro_cents,
                              team?.default_monthly_budget_micro_cents
                            )}
                          </Text>
                        </TableData>
                        <TableData style={colStyles.cloud}>
                          <Text style={{ fontSize: 12, color: "#4b5563" }}>
                            {formatLimitNumber(
                              s.cloud_rpm_limit,
                              team?.default_cloud_rpm_limit
                            )}{" "}
                            RPM /{" "}
                            {formatLimitNumber(
                              s.cloud_tpm_limit,
                              team?.default_cloud_tpm_limit
                            )}{" "}
                            TPM
                          </Text>
                        </TableData>
                        <TableData style={colStyles.local}>
                          <Text style={{ fontSize: 12, color: "#4b5563" }}>
                            {formatLimitNumber(
                              s.local_rpm_limit,
                              team?.default_local_rpm_limit
                            )}{" "}
                            RPM /{" "}
                            {formatLimitNumber(
                              s.local_tpm_limit,
                              team?.default_local_tpm_limit
                            )}{" "}
                            TPM
                          </Text>
                        </TableData>
                        <TableData style={colStyles.priority}>
                          <Text
                            style={{
                              fontSize: 12,
                              color: "#4b5563",
                              fontWeight: "600",
                            }}
                          >
                            {key.default_priority}
                          </Text>
                        </TableData>
                        <TableData style={colStyles.actions}>
                          <HStack style={{ gap: 16 }}>
                            <Pressable onPress={() => setSelectedKey(key)}>
                              <Icon as={EditIcon} size="sm" color="#64748b" />
                            </Pressable>
                            {canEdit && (
                              <Pressable
                                onPress={() =>
                                  setDeleteConfig({
                                    id: key.id,
                                    title: "Delete Application Key",
                                    message: `Are you sure you want to delete "${key.name}"? This action breaks all connected services immediately.`,
                                  })
                                }
                              >
                                <Icon
                                  as={TrashIcon}
                                  size="sm"
                                  className="text-typography-400"
                                />
                              </Pressable>
                            )}
                          </HStack>
                        </TableData>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </Box>
          </ScrollView>
        </Box>
      )}

      <ApiKeyModal
        visible={!!selectedKey}
        onClose={() => setSelectedKey(null)}
        apiKeyData={selectedKey}
        team={team}
        canEdit={canEditKeySettings}
        onSaved={onRefresh}
      />

      <ConfirmDeleteModal
        visible={!!deleteConfig}
        onClose={() => setDeleteConfig(null)}
        onConfirm={confirmDelete}
        title={deleteConfig?.title || ""}
        message={deleteConfig?.message || ""}
      />

      <BaseModal
        visible={createVisible}
        onClose={() => {
          setCreateVisible(false);
          resetCreateForm();
        }}
        maxWidth={600}
      >
        <VStack space="xl" style={{ padding: 8 }}>
          <Text style={{ fontWeight: "700", fontSize: 20 }}>
            New Application Key
          </Text>

          <HStack space="md">
            <VStack style={{ flex: 1 }} space="xs">
              <Text style={{ fontSize: 12, fontWeight: "600" }}>
                Environment <Text style={{ color: "red" }}>*</Text>
              </Text>
              <Input variant="outline">
                <InputField
                  placeholder="prod, dev..."
                  value={newKeyEnv}
                  onChangeText={setNewKeyEnv}
                />
              </Input>
            </VStack>
            <VStack style={{ flex: 1 }} space="xs">
              <Text style={{ fontSize: 12, fontWeight: "600" }}>
                Request Priority
              </Text>
              <Input variant="outline">
                <InputField
                  value={newKeyPrio}
                  onChangeText={setNewKeyPrio}
                  keyboardType="numeric"
                />
              </Input>
            </VStack>
          </HStack>

          {canEditKeySettings && (
            <>
              <View className="my-1 h-px w-full bg-outline-200" />

              <VStack space="md">
                <HStack space="md">
                  <VStack style={{ flex: 1 }} space="xs">
                    <Text style={{ fontSize: 12, fontWeight: "600" }}>
                      Monthly Budget ($)
                    </Text>
                    <Input variant="outline">
                      <InputField
                        placeholder={
                          team?.default_monthly_budget_micro_cents
                            ? `Default: ${formatMicroCentsToDollars(team.default_monthly_budget_micro_cents)}`
                            : "Unlimited"
                        }
                        value={newKeyBudget}
                        onChangeText={setNewKeyBudget}
                        keyboardType="decimal-pad"
                      />
                    </Input>
                  </VStack>

                  <VStack style={{ flex: 1 }} space="xs">
                    <Text
                      style={{
                        fontSize: 12,
                        fontWeight: "600",
                        color: "#374151",
                      }}
                    >
                      Cloud Limits (RPM / TPM)
                    </Text>
                    <HStack space="sm">
                      <Input variant="outline" style={{ flex: 1 }}>
                        <InputField
                          placeholder={
                            team?.default_cloud_rpm_limit
                              ? String(team.default_cloud_rpm_limit)
                              : "∞"
                          }
                          value={newKeyCloudRpm}
                          onChangeText={setNewKeyCloudRpm}
                          keyboardType="numeric"
                        />
                      </Input>
                      <Input variant="outline" style={{ flex: 1 }}>
                        <InputField
                          placeholder={
                            team?.default_cloud_tpm_limit
                              ? String(team.default_cloud_tpm_limit)
                              : "∞"
                          }
                          value={newKeyCloudTpm}
                          onChangeText={setNewKeyCloudTpm}
                          keyboardType="numeric"
                        />
                      </Input>
                    </HStack>
                  </VStack>

                  <VStack style={{ flex: 1 }} space="xs">
                    <Text
                      style={{
                        fontSize: 12,
                        fontWeight: "600",
                        color: "#374151",
                      }}
                    >
                      Local Limits (RPM / TPM)
                    </Text>
                    <HStack space="sm">
                      <Input variant="outline" style={{ flex: 1 }}>
                        <InputField
                          placeholder={
                            team?.default_local_rpm_limit
                              ? String(team.default_local_rpm_limit)
                              : "∞"
                          }
                          value={newKeyLocalRpm}
                          onChangeText={setNewKeyLocalRpm}
                          keyboardType="numeric"
                        />
                      </Input>
                      <Input variant="outline" style={{ flex: 1 }}>
                        <InputField
                          placeholder={
                            team?.default_local_tpm_limit
                              ? String(team.default_local_tpm_limit)
                              : "∞"
                          }
                          value={newKeyLocalTpm}
                          onChangeText={setNewKeyLocalTpm}
                          keyboardType="numeric"
                        />
                      </Input>
                    </HStack>
                  </VStack>
                </HStack>
              </VStack>
            </>
          )}

          {createError && (
            <Text style={{ color: "#e63535", fontSize: 13 }}>{createError}</Text>
          )}

          <HStack
            space="md"
            style={{ justifyContent: "flex-end", marginTop: 8 }}
          >
            <Button
              variant="outline"
              onPress={() => {
                setCreateVisible(false);
                resetCreateForm();
              }}
            >
              <ButtonText>Cancel</ButtonText>
            </Button>
            <Button
              onPress={handleCreateKey}
              disabled={!newKeyEnv.trim() || isSaving}
            >
              {isSaving ? (
                <ActivityIndicator color="#fff" style={{ marginRight: 8 }} />
              ) : null}
              <ButtonText>Create App Key</ButtonText>
            </Button>
          </HStack>
        </VStack>
      </BaseModal>
    </VStack>
  );
}
