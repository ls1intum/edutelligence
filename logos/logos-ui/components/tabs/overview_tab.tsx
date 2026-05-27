import React from "react";
import { View } from "react-native";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Text } from "@/components/ui/text";
import { Box } from "@/components/ui/box";

export function Overview_tab({ team, membersCount, applicationKeysCount, budgetUsedMicroCents = 0 }: any) {
    if (!team) return null;

    const formatBudget = (microCents: number | null | undefined) => {
      if (microCents === null || microCents === undefined) return "No Limit";
      return `$${(microCents / 100000000).toFixed(2)}`;
    };

    const formatTpm = (tpm: number | null | undefined) => {
        if (!tpm) return "Unlimited";
        return tpm >= 1000 ? `${(tpm / 1000).toFixed(0)}k` : tpm.toString();
    };

    const limit = team.team_monthly_budget_micro_cents;
    const percentage = limit ? Math.min((budgetUsedMicroCents / limit) * 100, 100) : 0;
    const barColor = percentage >= 90 ? "#EF4444" : "#5B7CFA";

    return (
      <VStack space="xl">
        <VStack space="sm">
          <Text style={{ fontWeight: "700", fontSize: 16 }}>Basic stats</Text>
          <HStack space="md">
            <Box className="flex-1 rounded-lg border border-outline-200 bg-secondary-100 p-4">
              <Text
                style={{ fontSize: 13, color: "#6b7280", fontWeight: "600" }}
              >
                Members
              </Text>
              <Text
                style={{
                  fontSize: 24,
                  fontWeight: "bold",
                  color: "#111827",
                  marginTop: 4,
                }}
              >
                {membersCount}
              </Text>
            </Box>
            <Box className="flex-1 rounded-lg border border-outline-200 bg-secondary-100 p-4">
              <Text
                style={{ fontSize: 13, color: "#6b7280", fontWeight: "600" }}
              >
                Application Keys
              </Text>
              <Text
                style={{
                  fontSize: 24,
                  fontWeight: "bold",
                  color: "#111827",
                  marginTop: 4,
                }}
              >
                {applicationKeysCount}
              </Text>
            </Box>
          </HStack>
        </VStack>

        <VStack space="sm">
          <Text style={{ fontWeight: "700", fontSize: 16 }}>
            Monthly Team Budget (Member Only)
          </Text>
          <Box
            style={{
              padding: 16,
              borderRadius: 8,
              borderWidth: 1,
              borderColor: "#e2e8f0",
              backgroundColor: "#fff",
            }}
          >
            <HStack
              style={{ justifyContent: "space-between", marginBottom: 12 }}
            >
              <Text
                style={{ fontSize: 13, color: "#6b7280", fontWeight: "600" }}
              >
                Current Usage
              </Text>
              <Text style={{ fontSize: 14, color: "#111827" }}>
                {formatBudget(budgetUsedMicroCents)} / {formatBudget(limit)}
              </Text>
            </HStack>

            {limit ? (
              <View
                style={{
                  height: 10,
                  backgroundColor: "#f1f5f9",
                  borderRadius: 5,
                  overflow: "hidden",
                }}
              >
                <View
                  style={{
                    width: `${percentage}%`,
                    height: "100%",
                    backgroundColor: barColor,
                  }}
                />
              </View>
            ) : (
              <View
                style={{
                  backgroundColor: "#dcfce3",
                  alignSelf: "flex-start",
                  paddingHorizontal: 8,
                  paddingVertical: 4,
                  borderRadius: 6,
                }}
              >
                <Text
                  style={{ fontSize: 12, color: "#5B7CFA", fontWeight: "600" }}
                >
                  Unlimited Budget
                </Text>
              </View>
            )}
          </Box>
        </VStack>

        <VStack space="sm">
          <Text style={{ fontWeight: "700", fontSize: 16 }}>
            Default Limits
          </Text>
          <HStack space="md">
            <Box
              style={{
                flex: 1,
                padding: 16,
                borderRadius: 8,
                borderWidth: 1,
                borderColor: "#e2e8f0",
                backgroundColor: "#fff",
              }}
            >
              <Text style={{ fontWeight: "600", color: "#4b5563" }}>
                Default Key Budget
              </Text>
              <Text style={{ fontSize: 18, fontWeight: "700", marginTop: 4 }}>
                {team.default_monthly_budget_micro_cents
                  ? formatBudget(team.default_monthly_budget_micro_cents)
                  : "Unlimited"}
              </Text>
            </Box>
            <Box
              style={{
                flex: 1,
                padding: 16,
                borderRadius: 8,
                borderWidth: 1,
                borderColor: "#e2e8f0",
                backgroundColor: "#fff",
              }}
            >
              <Text style={{ fontWeight: "600", color: "#4b5563" }}>
                Cloud RPM / TPM
              </Text>
              <Text style={{ fontSize: 16, fontWeight: "700", marginTop: 4 }}>
                {team.default_cloud_rpm_limit || "∞"} /{" "}
                {formatTpm(team.default_cloud_tpm_limit)}
              </Text>
            </Box>
            <Box
              style={{
                flex: 1,
                padding: 16,
                borderRadius: 8,
                borderWidth: 1,
                borderColor: "#e2e8f0",
                backgroundColor: "#fff",
              }}
            >
              <Text style={{ fontWeight: "600", color: "#4b5563" }}>
                Local RPM / TPM
              </Text>
              <Text style={{ fontSize: 16, fontWeight: "700", marginTop: 4 }}>
                {team.default_local_rpm_limit || "∞"} /{" "}
                {formatTpm(team.default_local_tpm_limit)}
              </Text>
            </Box>
          </HStack>
        </VStack>
      </VStack>
    );
}