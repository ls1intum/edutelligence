import React, { useMemo, useState } from "react";
import { View } from "react-native";

import { Text } from "@/components/ui/text";
import { HStack } from "@/components/ui/hstack";
import { VStack } from "@/components/ui/vstack";
import {
  Select,
  SelectBackdrop,
  SelectContent,
  SelectInput,
  SelectItem,
  SelectPortal,
  SelectTrigger,
} from "@/components/ui/select";
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
};

function memoryBar(usedMb: number, totalMb: number, color: string) {
  const pct = totalMb > 0 ? Math.min(100, (usedMb / totalMb) * 100) : 0;
  return (
    <View className="h-2.5 w-full overflow-hidden rounded-full bg-background-300 dark:bg-background-700">
      <View
        className="h-full rounded-full"
        style={{ width: `${pct}%`, backgroundColor: color }}
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

  const label =
    device.name
      ? `GPU ${index}: ${device.name}`
      : `GPU ${device.device_id || index}`;

  return (
    <View className="mb-3 rounded-xl border border-outline-200 bg-background-50 p-3 dark:border-outline-700 dark:bg-background-900">
      <HStack className="mb-2 items-center justify-between">
        <Text className="text-sm font-semibold text-typography-900 dark:text-typography-50" numberOfLines={1}>
          {label}
        </Text>
        <HStack className="items-center gap-2">
          {tempC !== null && (
            <View
              className="rounded-full px-2 py-0.5"
              style={{ backgroundColor: `${tempColor(tempC)}22` }}
            >
              <Text className="text-xs font-medium" style={{ color: tempColor(tempC) }}>
                {Math.round(tempC)}°C
              </Text>
            </View>
          )}
          {powerW !== null && (
            <View className="rounded-full bg-background-200 px-2 py-0.5 dark:bg-background-700">
              <Text className="text-xs text-typography-600 dark:text-typography-400">
                {Math.round(powerW)}W
              </Text>
            </View>
          )}
        </HStack>
      </HStack>

      {/* Memory bar */}
      <VStack className="mb-2 gap-1">
        <HStack className="items-center justify-between">
          <Text className="text-xs text-typography-500 dark:text-typography-400">Memory</Text>
          <Text className="text-xs text-typography-700 dark:text-typography-300">
            {formatMb(device.memory_used_mb)} / {formatMb(device.memory_total_mb)} ({Math.round(usedPct)}%)
          </Text>
        </HStack>
        {memoryBar(device.memory_used_mb, device.memory_total_mb, "#3B82F6")}
      </VStack>

      {/* Utilization bar */}
      {utilizationPct !== null && (
        <VStack className="gap-1">
          <HStack className="items-center justify-between">
            <Text className="text-xs text-typography-500 dark:text-typography-400">Utilization</Text>
            <Text className="text-xs text-typography-700 dark:text-typography-300">
              {Math.round(utilizationPct)}%
            </Text>
          </HStack>
          <View className="h-2.5 w-full overflow-hidden rounded-full bg-background-300 dark:bg-background-700">
            <View
              className="h-full rounded-full bg-emerald-500"
              style={{ width: `${Math.min(100, utilizationPct)}%` }}
            />
          </View>
        </VStack>
      )}
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
  return (
    <View className="mb-3 rounded-xl border border-outline-200 bg-background-50 p-3 dark:border-outline-700 dark:bg-background-900">
      <Text className="mb-2 text-sm font-semibold text-typography-900 dark:text-typography-50">
        GPU Memory (aggregate)
      </Text>
      <VStack className="gap-1">
        <HStack className="items-center justify-between">
          <Text className="text-xs text-typography-500">Memory</Text>
          <Text className="text-xs text-typography-700 dark:text-typography-300">
            {formatMb(usedMb)} used / {formatMb(totalMb)} total
          </Text>
        </HStack>
        {memoryBar(usedMb, totalMb, "#3B82F6")}
      </VStack>
      <Text className="mt-2 text-xs text-typography-400">
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

  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);

  const activeProvider = useMemo(() => {
    if (selectedProvider && providers.includes(selectedProvider)) return selectedProvider;
    return providers[0] ?? null;
  }, [selectedProvider, providers]);

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
      {/* Provider selector */}
      {providers.length > 1 && (
        <Select
          selectedValue={activeProvider ?? ""}
          onValueChange={(val) => setSelectedProvider(val || null)}
        >
          <SelectTrigger className="rounded-full border border-outline-200 bg-background-50 px-3 py-2 dark:border-outline-700 dark:bg-background-900">
            <SelectInput
              placeholder="Select provider"
              value={activeProvider ?? ""}
              className="text-typography-900 dark:text-typography-50"
            />
          </SelectTrigger>
          <SelectPortal>
            <SelectBackdrop />
            <SelectContent className="border border-outline-200 bg-background-50 dark:border-outline-700 dark:bg-background-900">
              {providers.map((p) => (
                <SelectItem key={p} label={p} value={p} />
              ))}
            </SelectContent>
          </SelectPortal>
        </Select>
      )}

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
