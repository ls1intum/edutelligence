import React, { useMemo } from "react";
import { View } from "react-native";

import { Text } from "@/components/ui/text";
import { HStack } from "@/components/ui/hstack";
import { VStack } from "@/components/ui/vstack";
import EmptyState from "@/components/statistics/empty-state";
import type { DeviceInfo, LaneSignalData } from "@/components/statistics/types";
import type { VramV2Sample } from "@/hooks/use-stats-websocket-v2";

type ProviderMeta = {
  connected?: boolean;
  connection_state?: string;
};

type WorkerGpuPanelProps = {
  providerLatestSamples: Record<string, VramV2Sample | null>;
  providerDevices: Record<string, DeviceInfo[]>;
  providerMeta: Record<string, ProviderMeta>;
  lanesByProvider: Record<string, Record<string, LaneSignalData>>;
  // Provider selected by the shared selector in statistics.tsx. If null or not
  // in this panel's providers list, falls back to the first known provider.
  activeProvider: string | null;
};

function ProgressBar({ pct, color }: { pct: number; color: string }) {
  const w = Math.max(0, Math.min(100, pct));
  return (
    <View
      className="overflow-hidden rounded-full bg-secondary-200"
      style={{ height: 6, width: "100%" }}
    >
      <View
        className="h-full rounded-full"
        style={{ width: `${w}%`, backgroundColor: color }}
      />
    </View>
  );
}

function tempColor(temp: number | null): string {
  if (temp === null) return "#94A3B8";
  if (temp < 70) return "#10B981";
  if (temp < 85) return "#F59E0B";
  return "#EF4444";
}

function formatMb(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
}

type GpuCardProps = {
  device: DeviceInfo;
  index: number;
};

function GpuCard({ device, index }: GpuCardProps) {
  const usedPct =
    device.memory_total_mb > 0
      ? Math.min(100, (device.memory_used_mb / device.memory_total_mb) * 100)
      : 0;
  const utilizationPct = device.utilization_percent ?? null;
  const tempC = device.temperature_celsius;
  const powerW = device.power_draw_watts;

  return (
    <View
      className="rounded-xl border border-outline-200 bg-background-0"
      style={{ marginBottom: 10, paddingHorizontal: 16, paddingVertical: 14 }}
    >
      <HStack className="items-start gap-3">
        <HStack className="min-w-0 flex-1 items-center gap-2">
          <Text
            className="text-typography-500"
            style={{ fontSize: 11, fontWeight: "600" }}
          >
            GPU {index}
          </Text>
          <Text
            className="text-sm font-medium text-typography-900"
            numberOfLines={1}
            style={{ flexShrink: 1 }}
          >
            {device.name || device.device_id}
          </Text>
        </HStack>
        <HStack className="shrink-0 items-center gap-1.5">
          {tempC !== null && (
            <View
              className="rounded-md"
              style={{ backgroundColor: `${tempColor(tempC)}1f`, paddingHorizontal: 6, height: 20, justifyContent: "center" }}
            >
              <Text
                style={{ fontSize: 11, fontWeight: "500", color: tempColor(tempC) }}
              >
                {Math.round(tempC)}°C
              </Text>
            </View>
          )}
          {powerW !== null && (
            <View
              className="rounded-md bg-secondary-100"
              style={{ paddingHorizontal: 6, height: 20, justifyContent: "center" }}
            >
              <Text className="text-typography-500" style={{ fontSize: 11 }}>
                {Math.round(powerW)} W
              </Text>
            </View>
          )}
        </HStack>
      </HStack>

      <VStack className="mt-3 gap-2">
        <VStack className="gap-1">
          <HStack className="items-center justify-between">
            <Text className="text-[11px] text-typography-500">Memory</Text>
            <Text className="text-[11px] text-typography-900">
              {formatMb(device.memory_used_mb)} / {formatMb(device.memory_total_mb)} ({Math.round(usedPct)}%)
            </Text>
          </HStack>
          <ProgressBar pct={usedPct} color="#3B82F6" />
        </VStack>

        {utilizationPct !== null && (
          <VStack className="gap-1">
            <HStack className="items-center justify-between">
              <Text className="text-[11px] text-typography-500">Utilization</Text>
              <Text className="text-[11px] text-typography-900">
                {Math.round(utilizationPct)}%
              </Text>
            </HStack>
            <ProgressBar pct={utilizationPct} color="#10B981" />
          </VStack>
        )}
      </VStack>
    </View>
  );
}

function SyntheticGpuCard({
  usedMb,
  totalMb,
  freeMb,
}: {
  usedMb: number;
  totalMb: number;
  freeMb: number;
}) {
  const pct = totalMb > 0 ? (usedMb / totalMb) * 100 : 0;
  return (
    <View
      className="rounded-xl border border-outline-200 bg-background-0"
      style={{ marginBottom: 10, paddingHorizontal: 16, paddingVertical: 14 }}
    >
      <Text
        className="text-typography-900"
        style={{ fontSize: 13, fontWeight: "600", marginBottom: 8 }}
      >
        GPU Memory (aggregate)
      </Text>
      <VStack className="gap-1">
        <HStack className="items-center justify-between">
          <Text className="text-[11px] text-typography-500">Memory</Text>
          <Text className="text-[11px] text-typography-900">
            {formatMb(usedMb)} used / {formatMb(totalMb)} total
          </Text>
        </HStack>
        <ProgressBar pct={pct} color="#3B82F6" />
      </VStack>
      <Text className="mt-2 text-[11px] text-typography-400">
        {formatMb(freeMb)} free
      </Text>
    </View>
  );
}

export default function WorkerGpuPanel({
  providerLatestSamples,
  providerDevices,
  providerMeta,
  lanesByProvider,
  activeProvider: activeProviderProp,
}: WorkerGpuPanelProps) {
  const providers = useMemo(
    () =>
      Object.keys(providerLatestSamples).sort((a, b) => {
        const aConnected = providerMeta[a]?.connection_state !== "offline" && providerMeta[a]?.connected !== false;
        const bConnected = providerMeta[b]?.connection_state !== "offline" && providerMeta[b]?.connected !== false;
        if (aConnected !== bConnected) return aConnected ? -1 : 1;
        return a.localeCompare(b);
      }),
    [providerLatestSamples, providerMeta]
  );

  const activeProvider = useMemo(() => {
    if (activeProviderProp && providers.includes(activeProviderProp)) return activeProviderProp;
    return providers[0] ?? null;
  }, [activeProviderProp, providers]);

  const isOffline =
    activeProvider
      ? providerMeta[activeProvider]?.connection_state === "offline" ||
        providerMeta[activeProvider]?.connected === false
      : false;

  const latestSample = activeProvider ? providerLatestSamples[activeProvider] : null;
  const devices: DeviceInfo[] = useMemo(() => {
    if (activeProvider && providerDevices[activeProvider]?.length) {
      return providerDevices[activeProvider];
    }
    // fallback: devices from latest sample's scheduler_signals
    const fromSignal = latestSample?.scheduler_signals?.provider?.devices;
    if (Array.isArray(fromSignal) && fromSignal.length) return fromSignal;
    return [];
  }, [activeProvider, providerDevices, latestSample]);

  const providerSignals = latestSample?.scheduler_signals?.provider;
  const nvidiaAvailable = providerSignals?.nvidia_smi_available ?? true;
  const deviceMode = providerSignals?.device_mode ?? null;
  const isDerived = deviceMode === "derived" || !nvidiaAvailable;

  const laneCount = Object.keys(lanesByProvider[activeProvider ?? ""] ?? {}).length;
  const loadedLanes = providerSignals?.loaded_lane_count ?? 0;
  const activeLanes = Object.values(lanesByProvider[activeProvider ?? ""] ?? {}).filter(
    (l) => l.runtime_state === "running" || l.active_requests > 0
  ).length;

  if (!providers.length) {
    return <EmptyState message="No providers connected." />;
  }

  return (
    <VStack className="w-full gap-3">
      {/* Status header */}
      <HStack className="flex-wrap items-center gap-2">
        {isOffline && (
          <View className="rounded-full bg-red-500/10 px-2 py-0.5">
            <Text className="text-xs text-red-500">offline</Text>
          </View>
        )}
        {isDerived && (
          <View className="rounded-full bg-amber-500/10 px-2 py-0.5">
            <Text className="text-xs text-amber-500">nvidia-smi unavailable — memory estimates only</Text>
          </View>
        )}
        {laneCount > 0 && (
          <View className="rounded-full bg-blue-500/10 px-2 py-0.5">
            <Text className="text-xs text-blue-500">
              {activeLanes} active / {loadedLanes} loaded / {laneCount} total lanes
            </Text>
          </View>
        )}
      </HStack>

      {/* GPU cards */}
      <View style={{ opacity: isOffline ? 0.5 : 1 }}>
        {devices.length > 0 ? (
          devices.map((device, idx) => (
            <GpuCard key={device.device_id || idx} device={device} index={idx} />
          ))
        ) : (
          <SyntheticGpuCard
            usedMb={providerSignals?.used_memory_mb ?? 0}
            totalMb={providerSignals?.total_memory_mb ?? 0}
            freeMb={providerSignals?.free_memory_mb ?? 0}
          />
        )}
      </View>
    </VStack>
  );
}
