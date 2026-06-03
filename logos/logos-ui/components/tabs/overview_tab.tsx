import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Text } from "@/components/ui/text";
import { Box } from "@/components/ui/box";
import {
  Icon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from "@/components/ui/icon";
import BudgetHistoryChart, {
  BudgetBucket,
} from "@/components/billing/budget-history-chart";
import { API_BASE } from "@/components/statistics/constants";

type OverviewTabProps = {
  team: any;
  membersCount: number;
  applicationKeysCount: number;
  developerKeysCount?: number;
  teamModelsCount?: number;
  budgetUsedMicroCents?: number;
  apiKey: string;
  teamId: number;
  isOwner: boolean;
};

type Preset = "day" | "week" | "month" | "half_year" | "year";
const PRESETS: { key: Preset; label: string }[] = [
  { key: "day", label: "Day" },
  { key: "week", label: "Week" },
  { key: "month", label: "Month" },
  { key: "half_year", label: "6 Months" },
  { key: "year", label: "Year" },
];

function computeRange(preset: Preset, offset: number): { start: Date; end: Date } {
  const now = new Date();
  switch (preset) {
    case "day": {
      const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset);
      return { start, end: new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset + 1) };
    }
    case "week": {
      const daysToMon = (now.getDay() + 6) % 7;
      const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - daysToMon + offset * 7);
      return { start, end: new Date(start.getFullYear(), start.getMonth(), start.getDate() + 7) };
    }
    case "month": {
      const start = new Date(now.getFullYear(), now.getMonth() + offset, 1);
      return { start, end: new Date(now.getFullYear(), now.getMonth() + offset + 1, 1) };
    }
    case "half_year": {
      const curHalfStart = now.getMonth() < 6 ? 0 : 6;
      const startM = curHalfStart + offset * 6;
      const start = new Date(now.getFullYear(), startM, 1);
      return { start, end: new Date(now.getFullYear(), startM + 6, 1) };
    }
    case "year": {
      const start = new Date(now.getFullYear() + offset, 0, 1);
      return { start, end: new Date(now.getFullYear() + offset + 1, 0, 1) };
    }
  }
}

function formatRangeLabel(preset: Preset, start: Date, end: Date): string {
  const endDay = new Date(end.getTime() - 1);
  switch (preset) {
    case "day":
      return start.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
    case "week":
      return `${start.toLocaleDateString("en-US", { month: "short", day: "numeric" })} – ${endDay.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`;
    case "month":
      return start.toLocaleDateString("en-US", { month: "long", year: "numeric" });
    case "half_year":
      return `${start.toLocaleDateString("en-US", { month: "short", year: "numeric" })} – ${endDay.toLocaleDateString("en-US", { month: "short", year: "numeric" })}`;
    case "year":
      return String(start.getFullYear());
  }
}

export function Overview_tab({
  team,
  membersCount,
  applicationKeysCount,
  budgetUsedMicroCents = 0,
  apiKey,
  teamId,
  isOwner,
}: OverviewTabProps) {
  const [preset, setPreset] = useState<Preset>("month");
  const [offset, setOffset] = useState(0);
  const budgetRange = useMemo(() => computeRange(preset, offset), [preset, offset]);
  const rangeLabel = useMemo(
    () => formatRangeLabel(preset, budgetRange.start, budgetRange.end),
    [preset, budgetRange]
  );
  const xAxisFormat =
    preset === "day" ? "%H:%M" : preset === "year" ? "%b %Y" : "%b %d";
  const barWidthMs: Record<Preset, number> = {
    day: 0.9 * 3600 * 1000,
    week: 0.9 * 86400 * 1000,
    month: 0.9 * 86400 * 1000,
    half_year: 0.9 * 7 * 86400 * 1000,
    year: 0.9 * 30 * 86400 * 1000,
  };
  const bw = barWidthMs[preset];
  const paddedRangeStart = budgetRange.start.getTime() - bw / 2;
  const paddedRangeEnd = budgetRange.end.getTime() + bw / 2;
  const [keyBuckets, setKeyBuckets] = useState<BudgetBucket[]>([]);
  const [keyTotals, setKeyTotals] = useState<
    Array<{ name: string; total_usd: number }>
  >([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const fetchKeyHistory = useCallback(async () => {
    if (!isOwner || !apiKey) return;
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const res = await fetch(
        `${API_BASE}/logosdb/billing/key_budget_history/${teamId}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", "logos-key": apiKey },
          body: JSON.stringify({
            start_iso: budgetRange.start.toISOString(),
            end_iso: budgetRange.end.toISOString(),
          }),
        }
      );
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const json = await res.json();
      const raw: Array<{
        api_key_id: number;
        api_key_name: string;
        bucket_ts: string;
        cost_micro_cents: number;
      }> = json.buckets ?? [];

      setKeyBuckets(
        raw.map((r) => ({
          seriesKey: r.api_key_name,
          bucketTs: new Date(r.bucket_ts).getTime(),
          costMicroCents: r.cost_micro_cents,
        }))
      );

      const totalsMap = new Map<string, number>();
      for (const r of raw) {
        totalsMap.set(
          r.api_key_name,
          (totalsMap.get(r.api_key_name) ?? 0) + r.cost_micro_cents
        );
      }
      setKeyTotals(
        Array.from(totalsMap.entries())
          .map(([name, mc]) => ({ name, total_usd: mc / 100_000_000 }))
          .sort((a, b) => b.total_usd - a.total_usd)
      );
    } catch (e) {
      setHistoryError(
        e instanceof Error ? e.message : "Failed to load budget history"
      );
    } finally {
      setHistoryLoading(false);
    }
  }, [apiKey, teamId, isOwner, budgetRange]);

  useEffect(() => {
    fetchKeyHistory();
  }, [fetchKeyHistory]);

    const formatBudget = (microCents: number | null | undefined) => {
      if (microCents === null || microCents === undefined) return "No Limit";
      return `$${(microCents / 100000000).toFixed(2)}`;
    };

    const formatTpm = (tpm: number | null | undefined) => {
        if (!tpm) return "Unlimited";
        return tpm >= 1000 ? `${(tpm / 1000).toFixed(0)}k` : tpm.toString();
    };

  if (!team) return null;

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

        {isOwner && (
          <VStack space="sm">
            <Text style={{ fontWeight: "700", fontSize: 16 }}>
              Budget History
            </Text>

            <HStack space="xs" style={{ flexWrap: "wrap" }}>
              {PRESETS.map((p) => (
                <Pressable
                  key={p.key}
                  onPress={() => {
                    setPreset(p.key);
                    setOffset(0);
                  }}
                  style={{
                    paddingHorizontal: 10,
                    paddingVertical: 4,
                    borderRadius: 6,
                    borderWidth: 1,
                    borderColor: preset === p.key ? "#5B7CFA" : "#e2e8f0",
                    backgroundColor: preset === p.key ? "#EFF3FF" : "#fff",
                  }}
                >
                  <Text
                    style={{
                      fontSize: 12,
                      color: preset === p.key ? "#5B7CFA" : "#374151",
                      fontWeight: preset === p.key ? "600" : "400",
                    }}
                  >
                    {p.label}
                  </Text>
                </Pressable>
              ))}
            </HStack>
            <HStack style={{ alignItems: "center" }} space="md">
              <Pressable
                onPress={() => setOffset((o) => o - 1)}
                style={{ padding: 2 }}
              >
                <Icon as={ChevronLeftIcon} size="md" color="#5B7CFA" />
              </Pressable>
              <Text
                style={{
                  fontSize: 12,
                  fontWeight: "600",
                  color: "#374151",
                  minWidth: 150,
                  textAlign: "center",
                }}
              >
                {rangeLabel}
              </Text>
              <Pressable
                onPress={() => setOffset((o) => o + 1)}
                disabled={offset >= 0}
                style={{ padding: 2, opacity: offset >= 0 ? 0.3 : 1 }}
              >
                <Icon as={ChevronRightIcon} size="md" color="#5B7CFA" />
              </Pressable>
            </HStack>

            <Box
              style={{
                padding: 16,
                borderRadius: 8,
                borderWidth: 1,
                borderColor: "#e2e8f0",
                backgroundColor: "#fff",
              }}
            >
              {historyLoading ? (
                <View style={{ alignItems: "center", paddingVertical: 32 }}>
                  <ActivityIndicator />
                </View>
              ) : historyError ? (
                <Text style={{ color: "#EF4444", fontSize: 13 }}>
                  {historyError}
                </Text>
              ) : (
                <BudgetHistoryChart
                  data={keyBuckets}
                  title="Spend by API Key"
                  height={280}
                  xAxisFormat={xAxisFormat}
                  rangeStart={paddedRangeStart}
                  rangeEnd={paddedRangeEnd}
                  barWidthMs={bw}
                />
              )}
            </Box>

            {!historyLoading &&
              !historyError &&
              keyTotals.some((t) => t.total_usd > 0) && (
                <Box
                  style={{
                    padding: 12,
                    borderRadius: 8,
                    borderWidth: 1,
                    borderColor: "#e2e8f0",
                    backgroundColor: "#fff",
                  }}
                >
                  {keyTotals
                    .filter((t) => t.total_usd > 0)
                    .map((t) => (
                      <HStack
                        key={t.name}
                        style={{
                          justifyContent: "space-between",
                          paddingVertical: 3,
                        }}
                      >
                        <Text style={{ fontSize: 12, color: "#374151" }}>
                          {t.name}
                        </Text>
                        <Text
                          style={{
                            fontSize: 12,
                            fontWeight: "600",
                            color: "#111827",
                          }}
                        >
                          ${t.total_usd.toFixed(6)}
                        </Text>
                      </HStack>
                    ))}
                </Box>
              )}
          </VStack>
        )}
      </VStack>
    );
}
