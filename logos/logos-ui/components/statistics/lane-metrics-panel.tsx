import React, { useMemo } from "react";
import { View } from "react-native";

import { Text } from "@/components/ui/text";
import { HStack } from "@/components/ui/hstack";
import { VStack } from "@/components/ui/vstack";
import EmptyState from "@/components/statistics/empty-state";
import { getLaneStateColor } from "@/components/statistics/constants";
import type { LaneSignalData } from "@/components/statistics/types";

const STATE_ORDER: Record<string, number> = {
  running: 0,
  loaded: 1,
  starting: 2,
  sleeping: 3,
  cold: 4,
  stopped: 5,
  error: 6,
};

function kvBarColor(pct: number): string {
  if (pct < 50) return "#10B981";
  if (pct < 80) return "#F59E0B";
  return "#EF4444";
}

function ttftColor(secs: number): string {
  if (secs < 0.2) return "#10B981";
  if (secs < 0.5) return "#F59E0B";
  return "#EF4444";
}

type LaneRowProps = {
  laneId: string;
  lane: LaneSignalData;
};

function LaneRow({ laneId, lane }: LaneRowProps) {
  const stateColor = getLaneStateColor(lane.runtime_state);
  const kvPct = lane.gpu_cache_usage_percent;
  const ttft = lane.ttft_p95_seconds;
  const isVllm = lane.vllm;

  return (
    <View className="mb-2 rounded-xl border border-outline-200 bg-background-50 p-3">
      <HStack className="mb-2 items-start justify-between gap-2">
        <HStack className="min-w-0 flex-1 items-center gap-2">
          {/* State indicator dot */}
          <View
            className="h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ backgroundColor: stateColor }}
          />
          <VStack className="min-w-0 flex-1">
            <Text
              className="text-sm font-medium text-typography-900"
              numberOfLines={1}
            >
              {laneId}
            </Text>
            <Text className="text-xs text-typography-500" numberOfLines={1}>
              {lane.model}
            </Text>
          </VStack>
        </HStack>

        <HStack className="shrink-0 items-center gap-1.5">
          {/* State badge */}
          <View
            className="rounded-full px-2 py-0.5"
            style={{ backgroundColor: `${stateColor}22` }}
          >
            <Text className="text-xs font-medium uppercase" style={{ color: stateColor }}>
              {lane.runtime_state}
            </Text>
          </View>
          {/* Backend type badge */}
          <View className={`rounded-full px-2 py-0.5 ${isVllm ? "bg-violet-500/10" : "bg-orange-500/10"}`}>
            <Text className={`text-xs font-medium ${isVllm ? "text-violet-500" : "text-orange-400"}`}>
              {isVllm ? "vLLM" : "Ollama"}
            </Text>
          </View>
        </HStack>
      </HStack>

      {isVllm ? (
        <VStack className="gap-2">
          {/* KV Cache bar */}
          {kvPct !== null ? (
            <VStack className="gap-1">
              <HStack className="items-center justify-between">
                <Text className="text-xs text-typography-500">KV Cache</Text>
                <Text className="text-xs font-medium" style={{ color: kvBarColor(kvPct) }}>
                  {kvPct.toFixed(1)}%
                </Text>
              </HStack>
              <View className="h-2 w-full overflow-hidden rounded-full bg-background-300">
                <View
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.min(100, kvPct)}%`,
                    backgroundColor: kvBarColor(kvPct),
                  }}
                />
              </View>
            </VStack>
          ) : (
            <Text className="text-xs text-typography-400">KV Cache: —</Text>
          )}

          {/* TTFT + queue info */}
          <HStack className="flex-wrap gap-3">
            {ttft !== null && (
              <HStack className="items-center gap-1">
                <Text className="text-xs text-typography-500">TTFT p95:</Text>
                <View
                  className="rounded-full px-1.5 py-0.5"
                  style={{ backgroundColor: `${ttftColor(ttft)}22` }}
                >
                  <Text className="text-xs font-medium" style={{ color: ttftColor(ttft) }}>
                    {ttft < 1 ? `${Math.round(ttft * 1000)}ms` : `${ttft.toFixed(2)}s`}
                  </Text>
                </View>
              </HStack>
            )}
            {lane.queue_waiting !== null && lane.queue_waiting !== undefined && (
              <Text className="text-xs text-typography-500">
                Queue: <Text className="text-typography-700">{lane.queue_waiting}</Text>
              </Text>
            )}
            {lane.requests_running !== null && lane.requests_running !== undefined && (
              <Text className="text-xs text-typography-500">
                Running: <Text className="text-typography-700">{lane.requests_running}</Text>
              </Text>
            )}
          </HStack>
        </VStack>
      ) : (
        <HStack className="flex-wrap gap-3">
          <Text className="text-xs text-typography-500">
            Active: <Text className="text-typography-700">{lane.active_requests}</Text>
          </Text>
          <Text className="text-xs text-typography-400">KV/TTFT: N/A (Ollama)</Text>
        </HStack>
      )}
    </View>
  );
}

type LaneMetricsPanelProps = {
  lanesByProvider: Record<string, Record<string, LaneSignalData>>;
  providerMeta: Record<string, { connected?: boolean; connection_state?: string }>;
  selectedProvider?: string | null;
};

export default function LaneMetricsPanel({
  lanesByProvider,
  providerMeta,
  selectedProvider,
}: LaneMetricsPanelProps) {
  const lanes = useMemo(() => {
    const providerName = selectedProvider ?? Object.keys(lanesByProvider)[0];
    if (!providerName) return [];
    const lanesForProvider = lanesByProvider[providerName] ?? {};
    return Object.entries(lanesForProvider).sort(([, a], [, b]) => {
      const aOrder = STATE_ORDER[a.runtime_state] ?? 99;
      const bOrder = STATE_ORDER[b.runtime_state] ?? 99;
      if (aOrder !== bOrder) return aOrder - bOrder;
      return a.model.localeCompare(b.model);
    });
  }, [lanesByProvider, selectedProvider]);

  if (!lanes.length) {
    return <EmptyState message="No lane data available yet." />;
  }

  return (
    <VStack className="w-full">
      {lanes.map(([laneId, lane]) => (
        <LaneRow key={laneId} laneId={laneId} lane={lane} />
      ))}
    </VStack>
  );
}
