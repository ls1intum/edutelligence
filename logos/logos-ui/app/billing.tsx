import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import { useAuth } from "@/components/auth-shell";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Text } from "@/components/ui/text";
import { Box } from "@/components/ui/box";
import { Icon, ChevronLeftIcon, ChevronRightIcon } from "@/components/ui/icon";
import BudgetHistoryChart, {
  BudgetBucket,
} from "@/components/billing/budget-history-chart";
import { API_BASE } from "@/components/statistics/constants";

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

type TeamTotal = { team_name: string; total_usd: number };

export default function Billing() {
  const { apiKey, role } = useAuth();
  const [preset, setPreset] = useState<Preset>("month");
  const [offset, setOffset] = useState(0);

  const dateRange = useMemo(() => computeRange(preset, offset), [preset, offset]);
  const rangeLabel = useMemo(
    () => formatRangeLabel(preset, dateRange.start, dateRange.end),
    [preset, dateRange]
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
  const paddedRangeStart = dateRange.start.getTime() - bw / 2;
  const paddedRangeEnd = dateRange.end.getTime() + bw / 2;

  const [buckets, setBuckets] = useState<BudgetBucket[]>([]);
  const [teamTotals, setTeamTotals] = useState<TeamTotal[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!apiKey || role !== "logos_admin") return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE}/logosdb/billing/team_budget_history`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", "logos-key": apiKey },
          body: JSON.stringify({
            start_iso: dateRange.start.toISOString(),
            end_iso: dateRange.end.toISOString(),
          }),
        }
      );
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const json = await res.json();
      const raw: Array<{
        team_id: number;
        team_name: string;
        bucket_ts: string;
        cost_micro_cents: number;
      }> = json.buckets ?? [];

      setBuckets(
        raw.map((r) => ({
          seriesKey: r.team_name,
          bucketTs: new Date(r.bucket_ts).getTime(),
          costMicroCents: r.cost_micro_cents,
        }))
      );

      const totalsMap = new Map<string, number>();
      for (const r of raw) {
        totalsMap.set(r.team_name, (totalsMap.get(r.team_name) ?? 0) + r.cost_micro_cents);
      }
      setTeamTotals(
        Array.from(totalsMap.entries())
          .map(([team_name, mc]) => ({ team_name, total_usd: mc / 100_000_000 }))
          .sort((a, b) => b.total_usd - a.total_usd)
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load billing data");
    } finally {
      setLoading(false);
    }
  }, [apiKey, role, dateRange]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (role !== "logos_admin") {
    return (
      <VStack className="w-full" space="lg">
        <Text size="2xl" className="text-center font-bold text-black dark:text-white">
          Billing Management
        </Text>
        <Box className="self-center rounded-2xl border border-outline-200 p-5 dark:border-outline-800 dark:bg-[#111]">
          <Text className="self-center text-gray-500 dark:text-gray-400">
            You do not have access to this page.
          </Text>
        </Box>
      </VStack>
    );
  }

  return (
    <VStack className="w-full" space="lg">
      <Text size="2xl" className="text-center font-bold text-black dark:text-white">
        Billing Management
      </Text>

      <VStack space="sm">
        <HStack space="xs" style={{ flexWrap: "wrap" }}>
          {PRESETS.map((p) => (
            <Pressable
              key={p.key}
              onPress={() => {
                setPreset(p.key);
                setOffset(0);
              }}
              style={{
                paddingHorizontal: 12,
                paddingVertical: 6,
                borderRadius: 6,
                borderWidth: 1,
                borderColor: preset === p.key ? "#5B7CFA" : "#e2e8f0",
                backgroundColor: preset === p.key ? "#EFF3FF" : "#fff",
              }}
            >
              <Text
                style={{
                  fontSize: 13,
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
          <Pressable onPress={() => setOffset((o) => o - 1)} style={{ padding: 4 }}>
            <Icon as={ChevronLeftIcon} size="md" style={{ color: "#5B7CFA" }} />
          </Pressable>
          <Text
            style={{
              fontSize: 14,
              fontWeight: "600",
              color: "#374151",
              minWidth: 170,
              textAlign: "center",
            }}
          >
            {rangeLabel}
          </Text>
          <Pressable
            onPress={() => setOffset((o) => o + 1)}
            disabled={offset >= 0}
            style={{ padding: 4, opacity: offset >= 0 ? 0.3 : 1 }}
          >
            <Icon as={ChevronRightIcon} size="md" style={{ color: "#5B7CFA" }} />
          </Pressable>
        </HStack>
      </VStack>

      <Box
        style={{
          borderRadius: 12,
          borderWidth: 1,
          borderColor: "#e2e8f0",
          backgroundColor: "#fff",
          padding: 16,
        }}
      >
        {loading ? (
          <View style={{ alignItems: "center", paddingVertical: 40 }}>
            <ActivityIndicator />
          </View>
        ) : error ? (
          <Text style={{ color: "#EF4444" }}>{error}</Text>
        ) : (
          <BudgetHistoryChart
            data={buckets}
            title="Team Budget Spend"
            height={340}
            xAxisFormat={xAxisFormat}
            rangeStart={paddedRangeStart}
            rangeEnd={paddedRangeEnd}
            barWidthMs={bw}
          />
        )}
      </Box>

      {!loading && !error && teamTotals.some((t) => t.total_usd > 0) && (
        <Box
          style={{
            borderRadius: 12,
            borderWidth: 1,
            borderColor: "#e2e8f0",
            backgroundColor: "#fff",
            padding: 16,
          }}
        >
          <Text style={{ fontWeight: "700", fontSize: 14, marginBottom: 10 }}>
            Total spend per team
          </Text>
          {teamTotals
            .filter((t) => t.total_usd > 0)
            .map((t) => (
              <HStack
                key={t.team_name}
                style={{ justifyContent: "space-between", paddingVertical: 4 }}
              >
                <Text style={{ fontSize: 13, color: "#374151" }}>{t.team_name}</Text>
                <Text style={{ fontSize: 13, fontWeight: "600", color: "#111827" }}>
                  ${t.total_usd.toFixed(6)}
                </Text>
              </HStack>
            ))}
        </Box>
      )}
    </VStack>
  );
}
