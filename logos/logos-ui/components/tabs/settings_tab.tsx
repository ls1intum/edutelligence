import React, { useState, useEffect } from "react";
import { View, ActivityIndicator } from "react-native";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Text } from "@/components/ui/text";
import { Button, ButtonText } from "@/components/ui/button";
import { Input, InputField } from "@/components/ui/input";
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

export function Settings_tab({
  team,
  canEdit,
  canEditLimits,
  apiKey,
  onRefresh,
  onDeleteTeam,
}: any) {
  const [teamBudget, setTeamBudget] = useState(
    formatMicroCentsToDollars(team?.team_monthly_budget_micro_cents)
  );
  const [defaultBudget, setDefaultBudget] = useState(
    formatMicroCentsToDollars(team?.default_monthly_budget_micro_cents)
  );

  const [cloudRpm, setCloudRpm] = useState(
    String(team?.default_cloud_rpm_limit || "")
  );
  const [cloudTpm, setCloudTpm] = useState(
    String(team?.default_cloud_tpm_limit || "")
  );
  const [localRpm, setLocalRpm] = useState(
    String(team?.default_local_rpm_limit || "")
  );
  const [localTpm, setLocalTpm] = useState(
    String(team?.default_local_tpm_limit || "")
  );

  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");

  useEffect(() => {
    if (team) {
      setTeamBudget(
        formatMicroCentsToDollars(team.team_monthly_budget_micro_cents)
      );
      setDefaultBudget(
        formatMicroCentsToDollars(team.default_monthly_budget_micro_cents)
      );
      setCloudRpm(String(team.default_cloud_rpm_limit || ""));
      setCloudTpm(String(team.default_cloud_tpm_limit || ""));
      setLocalRpm(String(team.default_local_rpm_limit || ""));
      setLocalTpm(String(team.default_local_tpm_limit || ""));
    }
  }, [team]);

  const handleSave = async () => {
    setIsSaving(true);
    setSaveMessage("");
    try {
      const payload = {
        team_monthly_budget_micro_cents: parseDollarsToMicroCents(teamBudget),
        default_monthly_budget_micro_cents:
          parseDollarsToMicroCents(defaultBudget),
        default_cloud_rpm_limit: cloudRpm.trim()
          ? parseInt(cloudRpm, 10)
          : null,
        default_cloud_tpm_limit: cloudTpm.trim()
          ? parseInt(cloudTpm, 10)
          : null,
        default_local_rpm_limit: localRpm.trim()
          ? parseInt(localRpm, 10)
          : null,
        default_local_tpm_limit: localTpm.trim()
          ? parseInt(localTpm, 10)
          : null,
      };

      const res = await fetch(`${API_BASE}/teams/${team.id}`, {
        method: "PATCH",
        headers: {
          "logos-key": apiKey,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error("Failed to save settings");

      setSaveMessage("Successfully updated settings!");
      if (onRefresh) onRefresh();

      setTimeout(() => setSaveMessage(""), 3000);
    } catch (error) {
      console.error(error);
      alert("Error saving settings.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <VStack space="xl">
      <VStack space="sm">
        <Text style={{ fontWeight: "700", fontSize: 16, color: "#111827" }}>
          Overall Team Limits
        </Text>
        <View
          style={{
            backgroundColor: "#f8fafc",
            padding: 16,
            borderRadius: 8,
            borderWidth: 1,
            borderColor: "#e2e8f0",
            marginTop: 4,
          }}
        >
          <VStack space="xs">
            <Text style={{ fontSize: 13, fontWeight: "600", color: "#374151" }}>
              Team Monthly Budget ($)
            </Text>
            <Input
              variant="outline"
              size="md"
              isDisabled={!canEditLimits}
              style={{ backgroundColor: "#fff" }}
            >
              <InputField
                value={teamBudget}
                onChangeText={setTeamBudget}
                keyboardType="decimal-pad"
                placeholder="e.g. 150 or 50.50 (leave empty for unlimited)"
              />
            </Input>
          </VStack>
        </View>
      </VStack>

      <VStack space="sm">
        <Text style={{ fontWeight: "700", fontSize: 16, color: "#111827" }}>
          Default Limits
        </Text>
        <Text style={{ fontSize: 13, color: "#6b7280" }}>
          Standard fallback limits assigned to newly created keys or members in
          this team.
        </Text>
        <View
          style={{
            backgroundColor: "#f8fafc",
            padding: 16,
            borderRadius: 8,
            borderWidth: 1,
            borderColor: "#e2e8f0",
            marginTop: 4,
          }}
        >
          <VStack space="lg">
            <VStack space="xs">
              <Text
                style={{ fontSize: 13, fontWeight: "600", color: "#374151" }}
              >
                Member Default Budget ($)
              </Text>
              <Input
                variant="outline"
                size="md"
                isDisabled={!canEditLimits}
                style={{ backgroundColor: "#fff" }}
              >
                <InputField
                  value={defaultBudget}
                  onChangeText={setDefaultBudget}
                  keyboardType="decimal-pad"
                  placeholder="e.g. 150 or 50.50 (leave empty for unlimited)"
                />
              </Input>
            </VStack>

            <VStack space="xs">
              <Text
                style={{ fontSize: 13, fontWeight: "600", color: "#374151" }}
              >
                Cloud Rate Limits
              </Text>
              <HStack space="md">
                <VStack space="xs" style={{ flex: 1 }}>
                  <Text style={{ fontSize: 12, color: "#6b7280" }}>RPM</Text>
                  <Input
                    variant="outline"
                    size="md"
                    isDisabled={!canEditLimits}
                    style={{ backgroundColor: "#fff" }}
                  >
                    <InputField
                      value={cloudRpm}
                      onChangeText={setCloudRpm}
                      keyboardType="numeric"
                      placeholder="Requests per minute"
                    />
                  </Input>
                </VStack>
                <VStack space="xs" style={{ flex: 1 }}>
                  <Text style={{ fontSize: 12, color: "#6b7280" }}>TPM</Text>
                  <Input
                    variant="outline"
                    size="md"
                    isDisabled={!canEditLimits}
                    style={{ backgroundColor: "#fff" }}
                  >
                    <InputField
                      value={cloudTpm}
                      onChangeText={setCloudTpm}
                      keyboardType="numeric"
                      placeholder="Tokens per minute"
                    />
                  </Input>
                </VStack>
              </HStack>
            </VStack>

            <VStack space="xs">
              <Text
                style={{ fontSize: 13, fontWeight: "600", color: "#374151" }}
              >
                Local Rate Limits
              </Text>
              <HStack space="md">
                <VStack space="xs" style={{ flex: 1 }}>
                  <Text style={{ fontSize: 12, color: "#6b7280" }}>RPM</Text>
                  <Input
                    variant="outline"
                    size="md"
                    isDisabled={!canEditLimits}
                    style={{ backgroundColor: "#fff" }}
                  >
                    <InputField
                      value={localRpm}
                      onChangeText={setLocalRpm}
                      keyboardType="numeric"
                      placeholder="Requests per minute"
                    />
                  </Input>
                </VStack>
                <VStack space="xs" style={{ flex: 1 }}>
                  <Text style={{ fontSize: 12, color: "#6b7280" }}>TPM</Text>
                  <Input
                    variant="outline"
                    size="md"
                    isDisabled={!canEditLimits}
                    style={{ backgroundColor: "#fff" }}
                  >
                    <InputField
                      value={localTpm}
                      onChangeText={setLocalTpm}
                      keyboardType="numeric"
                      placeholder="Tokens per minute"
                    />
                  </Input>
                </VStack>
              </HStack>
            </VStack>
          </VStack>
        </View>

        {(canEdit || canEditLimits) && (
          <HStack
            style={{
              alignItems: "center",
              justifyContent: "flex-end",
              marginTop: 16,
              width: "100%",
            }}
            space="md"
          >

            {canEdit && (
              <Button action="negative" variant="solid" onPress={onDeleteTeam}>
                <ButtonText>Delete Team</ButtonText>
              </Button>
            )}

            {canEditLimits && (
              <Button
                onPress={handleSave}
                disabled={isSaving}
                variant="solid"
                style={{ minWidth: 140 }}
              >
                {isSaving ? (
                  <ActivityIndicator color="#fff" style={{ marginRight: 8 }} />
                ) : null}
                <ButtonText>
                  {isSaving ? "Saving..." : "Save Settings"}
                </ButtonText>
              </Button>
            )}
          </HStack>
        )}
      </VStack>
    </VStack>
  );
}
