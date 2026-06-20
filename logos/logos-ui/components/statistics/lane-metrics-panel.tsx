import React, { useEffect, useMemo, useRef, useState } from "react";
import { Animated, View } from "react-native";

import { Text } from "@/components/ui/text";
import { HStack } from "@/components/ui/hstack";
import { VStack } from "@/components/ui/vstack";
import { Button, ButtonText } from "@/components/ui/button";
import EmptyState from "@/components/statistics/empty-state";
import { API_BASE, getLaneStateColor } from "@/components/statistics/constants";
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
  /** Immediately unload (stop) this lane, freeing its VRAM. */
  onUnload?: () => void;
  unloading?: boolean;
};

function LaneRow({ laneId, lane, onUnload, unloading }: LaneRowProps) {
  const stateColor = getLaneStateColor(lane.runtime_state);
  const kvPct = lane.gpu_cache_usage_percent;
  const ttft = lane.ttft_p95_seconds;
  const isVllm = lane.vllm;
  const isActive = lane.runtime_state === "running" || lane.runtime_state === "starting";

  // Halo pulse on the status dot for live lanes
  const halo = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (isActive) {
      const loop = Animated.loop(
        Animated.sequence([
          Animated.timing(halo, { toValue: 1, duration: 800, useNativeDriver: true }),
          Animated.timing(halo, { toValue: 0, duration: 800, useNativeDriver: true }),
        ])
      );
      loop.start();
      return () => loop.stop();
    }
    halo.setValue(0);
  }, [isActive, halo]);

  return (
    <View
      className="rounded-xl border border-outline-200 bg-background-0"
      style={{ marginBottom: 8, paddingHorizontal: 14, paddingVertical: 12 }}
    >
      <HStack className="items-start gap-2">
        {/* State indicator dot with optional pulsing halo */}
        <View style={{ width: 14, height: 14, marginTop: 4, alignItems: "center", justifyContent: "center" }}>
          {isActive && (
            <Animated.View
              pointerEvents="none"
              style={{
                position: "absolute",
                width: 14,
                height: 14,
                borderRadius: 7,
                backgroundColor: stateColor,
                opacity: halo.interpolate({ inputRange: [0, 1], outputRange: [0.18, 0.45] }),
                transform: [
                  { scale: halo.interpolate({ inputRange: [0, 1], outputRange: [1, 1.6] }) },
                ],
              }}
            />
          )}
          <View
            className="rounded-full"
            style={{ height: 8, width: 8, backgroundColor: stateColor }}
          />
        </View>

        <VStack className="min-w-0 flex-1 gap-1.5">
          <HStack className="items-center gap-2">
            <Text className="text-sm font-medium text-typography-900" numberOfLines={1}>
              {laneId}
            </Text>
            <Text
              style={{ fontSize: 10, fontWeight: "700", letterSpacing: 0.5, color: stateColor }}
            >
              {lane.runtime_state.toUpperCase()}
            </Text>
            <HStack className="items-center gap-2" style={{ marginLeft: "auto" }}>
              <View
                className={`rounded-md px-1.5 py-0.5 ${isVllm ? "bg-violet-500/10" : "bg-orange-500/10"}`}
              >
                <Text
                  className={`text-[10px] font-semibold uppercase tracking-wider ${isVllm ? "text-violet-500" : "text-orange-500"}`}
                >
                  {isVllm ? "vllm" : "ollama"}
                </Text>
              </View>
              {onUnload && (
                <Button
                  size="xs"
                  variant="outline"
                  action="negative"
                  onPress={onUnload}
                  isDisabled={unloading}
                >
                  <ButtonText className="text-red-500">
                    {unloading ? "Unloading…" : "Unload"}
                  </ButtonText>
                </Button>
              )}
            </HStack>
          </HStack>
          <Text className="text-xs text-typography-500" numberOfLines={1}>
            {lane.model}
          </Text>

          {isVllm ? (
            <VStack className="mt-1 gap-2">
              {kvPct !== null ? (
                <VStack className="gap-1">
                  <HStack className="items-center justify-between">
                    <Text className="text-[11px] text-typography-500">KV cache</Text>
                    <Text className="text-[11px] font-medium" style={{ color: kvBarColor(kvPct) }}>
                      {kvPct.toFixed(1)}%
                    </Text>
                  </HStack>
                  <View
                    className="overflow-hidden rounded-full bg-secondary-200"
                    style={{ height: 6, width: "100%" }}
                  >
                    <View
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.min(100, kvPct)}%`,
                        backgroundColor: kvBarColor(kvPct),
                      }}
                    />
                  </View>
                </VStack>
              ) : null}

              <HStack className="flex-wrap items-center" style={{ columnGap: 12, rowGap: 4 }}>
                {ttft !== null && (
                  <Text className="text-[11px] text-typography-500">
                    TTFT p95{" "}
                    <Text className="font-medium" style={{ color: ttftColor(ttft) }}>
                      {ttft < 1 ? `${Math.round(ttft * 1000)}ms` : `${ttft.toFixed(2)}s`}
                    </Text>
                  </Text>
                )}
                {lane.queue_waiting !== null && lane.queue_waiting !== undefined && (
                  <Text className="text-[11px] text-typography-500">
                    Queue <Text className="text-typography-900">{lane.queue_waiting}</Text>
                  </Text>
                )}
                {lane.requests_running !== null && lane.requests_running !== undefined && (
                  <Text className="text-[11px] text-typography-500">
                    Running <Text className="text-typography-900">{lane.requests_running}</Text>
                  </Text>
                )}
              </HStack>
            </VStack>
          ) : (
            <Text className="mt-1 text-[11px] text-typography-500">
              Active <Text className="text-typography-900">{lane.active_requests}</Text> · KV/TTFT n/a
            </Text>
          )}
        </VStack>
      </HStack>
    </View>
  );
}

type LaneMetricsPanelProps = {
  lanesByProvider: Record<string, Record<string, LaneSignalData>>;
  providerMeta: Record<
    string,
    { connected?: boolean; connection_state?: string; provider_id?: number }
  >;
  selectedProvider?: string | null;
  apiKey?: string | null;
};

export default function LaneMetricsPanel({
  lanesByProvider,
  providerMeta,
  selectedProvider,
  apiKey,
}: LaneMetricsPanelProps) {
  const providerName = selectedProvider ?? Object.keys(lanesByProvider)[0];
  const lanes = useMemo(() => {
    if (!providerName) return [];
    const lanesForProvider = lanesByProvider[providerName] ?? {};
    return Object.entries(lanesForProvider).sort(([, a], [, b]) => {
      const aOrder = STATE_ORDER[a.runtime_state] ?? 99;
      const bOrder = STATE_ORDER[b.runtime_state] ?? 99;
      if (aOrder !== bOrder) return aOrder - bOrder;
      return a.model.localeCompare(b.model);
    });
  }, [lanesByProvider, providerName]);

  const providerId = providerName
    ? providerMeta[providerName]?.provider_id ?? null
    : null;
  const providerOnline = providerName
    ? providerMeta[providerName]?.connection_state !== "offline" &&
      providerMeta[providerName]?.connected !== false
    : false;
  const canUnload = !!apiKey && providerId != null && providerOnline;

  const [unloadingLaneId, setUnloadingLaneId] = useState<string | null>(null);
  const [unloadError, setUnloadError] = useState<string | null>(null);

  const handleUnload = async (laneId: string) => {
    if (!apiKey || providerId == null || unloadingLaneId) return;
    setUnloadingLaneId(laneId);
    setUnloadError(null);
    try {
      const resp = await fetch(`${API_BASE}/logosdb/providers/logosnode/lanes/delete`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          logos_key: apiKey,
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          logos_key: apiKey,
          provider_id: providerId,
          lane_id: laneId,
        }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({} as Record<string, unknown>));
        const detail = typeof body?.error === "string" ? body.error : `HTTP ${resp.status}`;
        setUnloadError(`Unload of ${laneId} failed: ${detail}`);
      }
      // On success the lane disappears from the next runtime status push —
      // no local state to update beyond clearing the spinner.
    } catch (e) {
      const message = e instanceof Error ? e.message : "Request failed";
      setUnloadError(`Unload of ${laneId} failed: ${message}`);
    } finally {
      setUnloadingLaneId(null);
    }
  };

  if (!lanes.length) {
    return <EmptyState message="No lane data available yet." />;
  }

  return (
    <VStack className="w-full">
      {unloadError && (
        <View className="mb-2 rounded-md bg-red-500/10 px-3 py-1.5">
          <Text className="text-xs text-red-500">{unloadError}</Text>
        </View>
      )}
      {lanes.map(([laneId, lane]) => (
        <LaneRow
          key={laneId}
          laneId={laneId}
          lane={lane}
          onUnload={canUnload ? () => handleUnload(laneId) : undefined}
          unloading={unloadingLaneId === laneId}
        />
      ))}
    </VStack>
  );
}
