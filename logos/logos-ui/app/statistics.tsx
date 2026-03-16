import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ActivityIndicator,
  Animated,
  Easing,
  LayoutAnimation,
  Platform,
  RefreshControl,
  ScrollView,
  View,
} from "react-native";
import { PieChart } from "react-native-gifted-charts";

import { useAuth } from "@/components/auth-shell";
import PlotlyPieChart from "@/components/statistics/plotly-pie-chart";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonIcon } from "@/components/ui/button";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import {
  Select,
  SelectBackdrop,
  SelectContent,
  SelectInput,
  SelectItem,
  SelectPortal,
  SelectTrigger,
} from "@/components/ui/select";

import { CloseIcon } from "@/components/ui/icon";
import type { RequestEventStats } from "@/components/statistics/types";
import ChartCard from "@/components/statistics/chart-card";
import EmptyState from "@/components/statistics/empty-state";
import InteractiveZoomableChart from "@/components/statistics/interactive-zoomable-chart";
import VramChart from "@/components/statistics/vram-chart";
import PlotlyVramChart from "@/components/statistics/plotly-vram-chart";
import PlotlyRequestVolumeChart from "@/components/statistics/plotly-request-volume-chart";
import {
  API_BASE,
  CHART_PALETTE,
  getProviderColor,
} from "@/components/statistics/constants";
import {
  formatRangeLabel,
  applyTimeSeriesLabels,
  calculateDateRange,
} from "@/lib/utils/statistics";
import RequestStack, {
  RequestItem,
} from "@/components/statistics/request-stack";
import {
  useStatsWebSocketV2,
  VramV2Payload,
  TimelineInitPayload,
} from "@/hooks/use-stats-websocket-v2";

type VramSeriesPoint = {
  value: number;
  label: string;
  timestamp: number;
  used_vram_gb?: number;
  remaining_vram_gb?: number;
  total_vram_gb?: number;
  models_loaded?: number;
  loaded_model_names?: string[];
  loaded_models?: Array<{ name: string; size_gb: number }>;
  _empty?: boolean;
};

type TimelineEnqueueEvent = {
  request_id: string;
  enqueue_ts: string;
  timestamp_ms: number;
  is_cloud: boolean;
};

const buildVramSignature = (
  providers: Array<{ provider_id: number; name: string; data: Array<any> }>
): string =>
  [...providers]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((provider) => {
      const last = provider.data?.[provider.data.length - 1] || {};
      const models = Array.isArray(last.loaded_models)
        ? last.loaded_models
            .map((m: any) => `${m.name}:${m.size_vram_mb ?? m.size_vram ?? ""}`)
            .join("|")
        : "";
      return [
        provider.name,
        last.timestamp ?? "",
        last.used_vram_mb ?? last.vram_mb ?? "",
        last.remaining_vram_mb ?? "",
        last.total_vram_mb ?? "",
        models,
      ].join("::");
    })
    .join("||");

const getPieSizing = (width: number, scale = 1) => {
  const size = Math.min(width, 260) * scale;
  return {
    radius: size / 2.1,
    innerRadius: size / 3.2,
  };
};

const MODEL_SLICE_COLORS = [
  CHART_PALETTE.provider1,
  CHART_PALETTE.provider2,
  CHART_PALETTE.cloud,
  CHART_PALETTE.local,
];

const FREE_SLICE_COLOR = CHART_PALETTE.provider3;
const OTHER_SLICE_COLOR = CHART_PALETTE.total;

const BYTES_PER_MIB = 1024 * 1024;
const BYTES_PER_GB_DECIMAL = 1_000_000_000;

const toDecimalGb = (bytes: number) =>
  Number((bytes / BYTES_PER_GB_DECIMAL).toFixed(2));

const getLoadedModelsFromRaw = (
  raw: any
): Array<{ name: string; size_gb: number }> =>
  (raw?.loaded_models || [])
    .map((m: any) => {
      const sizeBytes =
        typeof m?.size_vram === "number"
          ? m.size_vram
          : typeof m?.size_vram_mb === "number"
            ? m.size_vram_mb * BYTES_PER_MIB
            : 0;
      return {
        name: m?.name ?? m?.model ?? "model",
        size_gb: toDecimalGb(sizeBytes),
      };
    })
    .filter((m: any) => m.size_gb > 0);

const parseVramSnapshot = (raw: any) => {
  const usedBytes =
    typeof raw?.vram_bytes === "number"
      ? raw.vram_bytes
      : (raw?.used_vram_mb || raw?.vram_mb || 0) * BYTES_PER_MIB;
  const configuredTotalBytes = (raw?.total_vram_mb || 0) * BYTES_PER_MIB;
  const remainingBytes =
    raw?.remaining_vram_mb != null
      ? raw.remaining_vram_mb * BYTES_PER_MIB
      : Math.max(0, configuredTotalBytes - usedBytes);
  const loadedModels = getLoadedModelsFromRaw(raw);

  return {
    usedGb: toDecimalGb(usedBytes),
    remainingGb: toDecimalGb(remainingBytes),
    totalGb: toDecimalGb(usedBytes + remainingBytes),
    modelsLoaded: raw?.models_loaded ?? loadedModels.length,
    loadedModels,
  };
};

const toVramSeriesPoint = (
  raw: any,
  timestamp: number,
  label = ""
): VramSeriesPoint => {
  const snapshot = parseVramSnapshot(raw);
  return {
    value: snapshot.remainingGb,
    label,
    timestamp,
    used_vram_gb: snapshot.usedGb,
    remaining_vram_gb: snapshot.remainingGb,
    total_vram_gb: snapshot.totalGb,
    models_loaded: snapshot.modelsLoaded,
    loaded_model_names: snapshot.loadedModels.map((m) => m.name),
    loaded_models: snapshot.loadedModels,
    _empty: false,
  };
};

const SKELETON_START_COLOR = "bg-background-300";

function StatisticsLegendSkeleton({ items = 3 }: { items?: number }) {
  return (
    <HStack className="flex-wrap items-center gap-4">
      {Array.from({ length: items }).map((_, idx) => (
        <HStack key={idx} className="items-center gap-2">
          <Skeleton
            variant="circular"
            startColor={SKELETON_START_COLOR}
            className="h-3 w-3"
          />
          <Skeleton
            variant="rounded"
            startColor={SKELETON_START_COLOR}
            className="h-3 w-20"
          />
        </HStack>
      ))}
    </HStack>
  );
}

function RecentRequestsSkeleton() {
  const itemSpecs = [
    {
      modelWidth: 228,
      ageWidth: 68,
      providerWidth: 84,
      totalWidth: 74,
      metaWidth: 240,
    },
    {
      modelWidth: 194,
      ageWidth: 68,
      providerWidth: 84,
      totalWidth: 68,
      metaWidth: 216,
    },
    {
      modelWidth: 188,
      ageWidth: 62,
      providerWidth: 84,
      totalWidth: 70,
      metaWidth: 228,
    },
    {
      modelWidth: 172,
      ageWidth: 52,
      providerWidth: 84,
      totalWidth: 66,
      metaWidth: 214,
    },
    {
      modelWidth: 210,
      ageWidth: 52,
      providerWidth: 84,
      totalWidth: 72,
      metaWidth: 236,
    },
  ];

  return (
    <VStack className="my-2.5 py-4">
      <Skeleton
        variant="rounded"
        startColor={SKELETON_START_COLOR}
        className="mb-2 h-7 w-48"
      />

      <View className="w-full">
        {itemSpecs.map((spec, idx) => (
          <View
            key={idx}
            className="mb-1.5 rounded-[10px] border-2 border-outline-200 bg-background-50 px-3 py-2.5"
          >
            <HStack className="w-full items-center" space="md">
              <VStack className="min-w-0 flex-1 gap-2">
                <HStack className="items-center gap-3">
                  <Skeleton
                    variant="rounded"
                    startColor={SKELETON_START_COLOR}
                    style={{ height: 22, width: spec.modelWidth }}
                  />
                  <Skeleton
                    variant="rounded"
                    startColor={SKELETON_START_COLOR}
                    style={{ height: 16, width: spec.ageWidth }}
                  />
                </HStack>
                <Skeleton
                  variant="rounded"
                  startColor={SKELETON_START_COLOR}
                  style={{ height: 20, width: spec.providerWidth }}
                />
              </VStack>

              <VStack className="shrink-0 items-end gap-2">
                <HStack className="items-center gap-2">
                  <Skeleton
                    variant="rounded"
                    startColor={SKELETON_START_COLOR}
                    style={{ height: 24, width: 56, borderRadius: 6 }}
                  />
                  <Skeleton
                    variant="rounded"
                    startColor={SKELETON_START_COLOR}
                    style={{ height: 28, width: spec.totalWidth }}
                  />
                </HStack>
                <Skeleton
                  variant="rounded"
                  startColor={SKELETON_START_COLOR}
                  style={{ height: 16, width: spec.metaWidth }}
                />
              </VStack>
            </HStack>
          </View>
        ))}
      </View>

      <Skeleton
        variant="rounded"
        startColor={SKELETON_START_COLOR}
        className="mt-2 h-7 w-28 self-center rounded-full"
      />
    </VStack>
  );
}

function VramUtilizationSkeleton() {
  return (
    <View className="my-2 rounded-2xl bg-secondary-200 p-4 shadow-hard-2">
      <View className="mb-4 gap-2">
        <Skeleton
          variant="rounded"
          startColor={SKELETON_START_COLOR}
          className="h-8 w-52"
        />
        <Skeleton
          variant="rounded"
          startColor={SKELETON_START_COLOR}
          className="h-5 w-72"
        />
      </View>

      <Skeleton
        variant="rounded"
        startColor={SKELETON_START_COLOR}
        className="h-12 w-full rounded-full"
      />

      <View className="my-4 h-px w-full bg-outline-200" />

      <View className="flex-col items-center justify-center gap-6 xl:flex-row xl:items-center xl:justify-between">
        <View className="relative items-center justify-center">
          <Skeleton
            variant="circular"
            startColor={SKELETON_START_COLOR}
            className="h-72 w-72"
          />
          <View
            className="absolute rounded-full bg-secondary-200"
            style={{ width: 128, height: 128 }}
          />
          <VStack className="absolute items-center gap-2">
            <Skeleton
              variant="rounded"
              startColor={SKELETON_START_COLOR}
              className="h-4 w-16"
            />
            <Skeleton
              variant="rounded"
              startColor={SKELETON_START_COLOR}
              className="h-8 w-24"
            />
            <Skeleton
              variant="rounded"
              startColor={SKELETON_START_COLOR}
              className="h-4 w-20"
            />
          </VStack>
        </View>

        <VStack className="gap-4 xl:min-w-[180px]">
          <StatisticsLegendSkeleton items={2} />
        </VStack>
      </View>
    </View>
  );
}

function RequestVolumeSkeleton() {
  return (
    <View className="my-2 rounded-2xl bg-secondary-200 p-4 shadow-hard-2">
      <View className="mb-4 gap-2">
        <Skeleton
          variant="rounded"
          startColor={SKELETON_START_COLOR}
          className="h-8 w-52"
        />
        <SkeletonText
          _lines={1}
          gap={2}
          startColor={SKELETON_START_COLOR}
          className="h-5 w-96 rounded-sm"
        />
      </View>

      <View className="self-start rounded-full border border-outline-300 bg-background-50 p-1">
        <HStack className="items-center gap-2">
          <Skeleton
            variant="rounded"
            startColor={SKELETON_START_COLOR}
            className="h-12 w-40 rounded-full"
          />
          <Skeleton
            variant="rounded"
            startColor={SKELETON_START_COLOR}
            className="h-12 w-32 rounded-full"
          />
        </HStack>
      </View>

      <View className="mt-6">
        <StatisticsLegendSkeleton items={2} />
      </View>

      <Skeleton
        variant="rounded"
        startColor={SKELETON_START_COLOR}
        className="mt-4 w-full rounded-xl"
        style={{ height: 360 }}
      />
    </View>
  );
}

function PieDistributionSkeleton({
  titleWidth = "w-40",
  legendItems = 3,
}: {
  titleWidth?: string;
  legendItems?: number;
}) {
  return (
    <View className="my-2 rounded-2xl bg-secondary-200 p-4 shadow-hard-2">
      <View className="mb-4 gap-2">
        <Skeleton
          variant="rounded"
          startColor={SKELETON_START_COLOR}
          className={`h-8 ${titleWidth}`}
        />
      </View>

      <View className="flex-col items-center justify-center gap-5 xl:flex-row xl:items-center xl:justify-between">
        <View className="relative items-center justify-center">
          <Skeleton
            variant="circular"
            startColor={SKELETON_START_COLOR}
            className="h-64 w-64"
          />
          <View
            className="absolute rounded-full bg-secondary-200"
            style={{ width: 92, height: 92 }}
          />
          <VStack className="absolute items-center gap-2">
            <Skeleton
              variant="rounded"
              startColor={SKELETON_START_COLOR}
              className="h-8 w-20"
            />
            <Skeleton
              variant="rounded"
              startColor={SKELETON_START_COLOR}
              className="h-4 w-16"
            />
          </VStack>
        </View>

        <VStack className="gap-3 xl:min-w-[180px]">
          <StatisticsLegendSkeleton items={legendItems} />
        </VStack>
      </View>
    </View>
  );
}

function VramRemainingSkeleton() {
  return (
    <View className="my-2 rounded-2xl bg-secondary-200 p-4 shadow-hard-2">
      <View className="mb-4 gap-2">
        <Skeleton
          variant="rounded"
          startColor={SKELETON_START_COLOR}
          className="h-8 w-52"
        />
        <Skeleton
          variant="rounded"
          startColor={SKELETON_START_COLOR}
          className="h-5 w-40"
        />
      </View>

      <View className="mb-4 flex-row flex-wrap items-center gap-3">
        <View className="rounded-full border border-outline-300 bg-background-50 p-1">
          <HStack className="items-center gap-2">
            <Skeleton
              variant="rounded"
              startColor={SKELETON_START_COLOR}
              className="h-10 w-32 rounded-full"
            />
            <Skeleton
              variant="rounded"
              startColor={SKELETON_START_COLOR}
              className="h-10 w-28 rounded-full"
            />
          </HStack>
        </View>

        <Skeleton
          variant="rounded"
          startColor={SKELETON_START_COLOR}
          className="h-5 w-48"
        />
      </View>

      <Skeleton
        variant="rounded"
        startColor={SKELETON_START_COLOR}
        className="w-full rounded-xl"
        style={{ height: 240 }}
      />

      <Skeleton
        variant="rounded"
        startColor={SKELETON_START_COLOR}
        className="mt-4 h-8 w-full rounded-sm"
      />
    </View>
  );
}

function StatisticsPageSkeleton() {
  return (
    <VStack space="md">
      <View className="w-full flex-col gap-3 xl:flex-row xl:items-start xl:gap-6">
        <View className="w-full xl:flex-1">
          <RecentRequestsSkeleton />
        </View>

        <View className="mx-4 hidden w-px self-stretch bg-outline-200 xl:flex" />

        <View className="w-full xl:flex-1">
          <VramUtilizationSkeleton />
        </View>
      </View>

      <View className="mt-5 h-[1px] w-full bg-outline-200" />

      <RequestVolumeSkeleton />

      <HStack space="sm" className="w-full">
        <View style={{ flex: 1 }}>
          <PieDistributionSkeleton titleWidth="w-40" legendItems={2} />
        </View>
        <View style={{ flex: 1 }}>
          <PieDistributionSkeleton titleWidth="w-40" legendItems={3} />
        </View>
      </HStack>

      <View className="my-8 h-[1px] w-full bg-outline-200" />

      <VramRemainingSkeleton />
    </VStack>
  );
}

export default function Statistics() {
  const { apiKey } = useAuth();
  const usePlotlyWeb = Platform.OS === "web";

  // State
  // Note: timeWindow is currently hardcoded to 30d. If you need to make this dynamic, convert to useState.
  const timeWindow: "30d" = "30d";
  const [customRange, setCustomRange] = useState<{
    start: Date;
    end: Date;
  } | null>(null);
  const [showRangeBadge, setShowRangeBadge] = useState(false);
  const rangeBadgeAnim = useRef(new Animated.Value(0)).current;
  const [resetZoomCounter, setResetZoomCounter] = useState(0);

  // Recent Requests Stack
  const [latestRequests, setLatestRequests] = useState<RequestItem[]>([]);
  const latestRequestsRef = useRef(latestRequests);
  useEffect(() => {
    latestRequestsRef.current = latestRequests;
  }, [latestRequests]);

  // Data
  const [stats, setStats] = useState<RequestEventStats | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [timelineEvents, setTimelineEvents] = useState<TimelineEnqueueEvent[]>(
    []
  );
  const timelineRangeRef = useRef<{
    startMs: number;
    endMs: number;
    bucketMs: number;
  } | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [hasResolvedStats, setHasResolvedStats] = useState(false);
  const [vramError, setVramError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [vramDayOffset, setVramDayOffset] = useState(0); // 0 = today, 1 = yesterday, etc.
  const [vramDataByProvider, setVramDataByProvider] = useState<{
    [url: string]: Array<VramSeriesPoint>;
  }>({});
  const [vramRawDataByProvider, setVramRawDataByProvider] = useState<{
    [url: string]: any[];
  }>({});
  const [selectedVramProvider, setSelectedVramProvider] = useState<
    string | null
  >(null);
  const [vramBaseline, setVramBaseline] = useState<any[]>([]);
  const [vramBucketSizeSec, setVramBucketSizeSec] = useState(10);
  const [vramTotalBuckets, setVramTotalBuckets] = useState(8640);
  const vramSignatureRef = useRef<string | null>(null);
  const currentVramUtcDayRef = useRef<string | null>(null);

  const vramProviders = useMemo(() => {
    const source = usePlotlyWeb ? vramRawDataByProvider : vramDataByProvider;
    return Object.keys(source).sort();
  }, [usePlotlyWeb, vramDataByProvider, vramRawDataByProvider]);

  useEffect(() => {
    if (!vramProviders.length) {
      setSelectedVramProvider(null);
      return;
    }
    if (
      !selectedVramProvider ||
      !vramProviders.includes(selectedVramProvider)
    ) {
      setSelectedVramProvider(vramProviders[0]);
    }
  }, [vramProviders, selectedVramProvider]);

  const latestVramSample = useMemo(() => {
    if (!selectedVramProvider) return null;

    // In Plotly mode data lives in vramRawDataByProvider (raw backend samples)
    if (usePlotlyWeb) {
      const rawSeries = vramRawDataByProvider[selectedVramProvider] || [];
      if (!rawSeries.length) return null;
      const raw = rawSeries[rawSeries.length - 1];
      if (!raw?.timestamp) return null;
      return toVramSeriesPoint(raw, new Date(raw.timestamp).getTime());
    }

    // Non-Plotly mode: use processed bucket data
    const series = vramDataByProvider[selectedVramProvider] || [];
    for (let i = series.length - 1; i >= 0; i -= 1) {
      const point = series[i];
      if (
        point &&
        !point._empty &&
        (point.used_vram_gb != null || point.remaining_vram_gb != null)
      ) {
        return point;
      }
    }
    return null;
  }, [
    selectedVramProvider,
    usePlotlyWeb,
    vramDataByProvider,
    vramRawDataByProvider,
  ]);

  const vramPieData = useMemo(() => {
    const usedGb = latestVramSample?.used_vram_gb ?? 0;
    const remainingGb = latestVramSample?.remaining_vram_gb ?? 0;
    const totalGb = latestVramSample?.total_vram_gb ?? usedGb + remainingGb;
    if (totalGb <= 0) return [];

    const modelSlices =
      latestVramSample?.loaded_models?.map((model, index) => ({
        value: model.size_gb,
        color: MODEL_SLICE_COLORS[index % MODEL_SLICE_COLORS.length],
        text: model.name,
      })) || [];

    const modeledUsed = modelSlices.reduce(
      (sum, slice) => sum + slice.value,
      0
    );
    const otherUsed = Math.max(0, usedGb - modeledUsed);

    const slices = [...modelSlices];
    if (otherUsed > 0.1) {
      slices.push({
        value: otherUsed,
        color: OTHER_SLICE_COLOR,
        text: modelSlices.length ? "Other" : "Used",
      });
    }

    slices.push({
      value: remainingGb,
      color: FREE_SLICE_COLOR,
      text: "Free",
    });

    return slices;
  }, [latestVramSample]);

  const vramSummary = useMemo(() => {
    const usedGb = latestVramSample?.used_vram_gb ?? 0;
    const remainingGb = latestVramSample?.remaining_vram_gb ?? 0;
    const totalGb = usedGb + remainingGb;
    const freePct = totalGb > 0 ? Math.round((remainingGb / totalGb) * 100) : 0;
    const models = latestVramSample?.loaded_models ?? [];
    const modelPreview =
      models.length > 0
        ? `${models
            .slice(0, 3)
            .map((m) => m.name)
            .join(
              ", "
            )}${models.length > 3 ? ` +${models.length - 3} more` : ""}`
        : "No models reported";
    return {
      usedGb,
      remainingGb,
      totalGb,
      freePct,
      modelsLoaded: latestVramSample?.models_loaded ?? models.length,
      modelPreview,
      models,
    };
  }, [latestVramSample]);

  // Helper functions for VRAM data

  const resolveVramBucketSize = useCallback(() => {
    return 10; // 10s buckets
  }, []);

  const processVramData = useCallback(
    (
      providers: Array<{ provider_id: number; name: string; data: Array<any> }>,
      dayAnchor?: Date
    ) => {
      const bucketSec = resolveVramBucketSize();
      const TOTAL_POINTS = Math.floor((24 * 3600) / bucketSec);

      // Determine start of the day (UTC)
      const dayStart = dayAnchor
        ? new Date(
            Date.UTC(
              dayAnchor.getUTCFullYear(),
              dayAnchor.getUTCMonth(),
              dayAnchor.getUTCDate()
            )
          )
        : new Date(new Date().setUTCHours(0, 0, 0, 0));
      const dayStartMs = dayStart.getTime();
      currentVramUtcDayRef.current = dayStart.toISOString().slice(0, 10);

      const processed: { [url: string]: Array<any> } = {};
      const timeline: Array<{ timestamp: number; label: string }> = [];

      // Build timeline skeleton
      for (let i = 0; i < TOTAL_POINTS; i++) {
        const ts = dayStartMs + i * bucketSec * 1000;
        // Label every hour based on bucket size
        const isHour = i % Math.max(1, Math.round(3600 / bucketSec)) === 0;
        const date = new Date(ts);
        const label = isHour
          ? date.toLocaleTimeString("en-GB", {
              hour: "2-digit",
              minute: "2-digit",
              timeZone: "UTC",
            })
          : "";
        timeline.push({ timestamp: ts, label });
      }

      const getBucketIndex = (ts: number) => {
        const diff = ts - dayStartMs;
        if (diff < 0) return -1;
        const idx = Math.floor(diff / (bucketSec * 1000));
        return idx < TOTAL_POINTS ? idx : -1;
      };

      providers.forEach((p) => {
        const buckets: Array<{ sum: number; count: number; raw: any } | null> =
          new Array(TOTAL_POINTS).fill(null);

        p.data.forEach((sample) => {
          const ts = new Date(sample.timestamp).getTime();
          const idx = getBucketIndex(ts);
          if (idx >= 0) {
            if (!buckets[idx]) buckets[idx] = { sum: 0, count: 0, raw: sample };
            const used = sample.vram_mb ?? 0;
            buckets[idx]!.sum += used;
            buckets[idx]!.count += 1;
            // Keep the sample with the latest timestamp within the bucket
            if (ts > new Date(buckets[idx]!.raw.timestamp).getTime()) {
              buckets[idx]!.raw = sample;
            }
          }
        });

        const lineData = timeline.map((t, i) => {
          const b = buckets[i];

          if (!b) {
            // Gaps go to ZERO as per user request
            return {
              value: 0,
              label: t.label,
              timestamp: t.timestamp,
              hideDataPoint: true,
              _empty: true,
            };
          }

          const raw = b.raw;
          return {
            ...toVramSeriesPoint(raw, t.timestamp, t.label),
            // Ensure we have properties needed for render
            hideDataPoint: false, // Show data points
            dataPointRadius: 2,
          };
        });
        processed[p.name] = lineData;
      });

      // Provide a baseline for the x-axis labels and total width.
      const baseline = timeline.map((t) => ({
        value: 0,
        label: t.label,
        timestamp: t.timestamp,
        _isBaseline: true,
      }));

      setVramBucketSizeSec(bucketSec);
      setVramTotalBuckets(TOTAL_POINTS);
      setVramBaseline(baseline);
      setVramDataByProvider(processed);
    },
    [resolveVramBucketSize]
  );

  const toVramChartPoint = useCallback(
    (raw: any, timestamp: number, label: string) => ({
      ...toVramSeriesPoint(raw, timestamp, label),
      hideDataPoint: false,
      dataPointRadius: 2,
    }),
    []
  );

  const appendVramDeltaSamples = useCallback(
    (
      providers: Array<{ provider_id: number; name: string; data: Array<any> }>
    ) => {
      if (!providers.length || !vramTotalBuckets) return false;
      const dayKey = currentVramUtcDayRef.current;
      if (!dayKey) return false;

      const dayStartMs = new Date(`${dayKey}T00:00:00.000Z`).getTime();
      const bucketMs = vramBucketSizeSec * 1000;
      const hourEvery = Math.max(1, Math.round(3600 / vramBucketSizeSec));

      let didUpdate = false;
      let needsFullRebuild = false;

      setVramDataByProvider((prev) => {
        let next = prev;

        for (const provider of providers) {
          const series = prev[provider.name];
          if (!series) {
            needsFullRebuild = true;
            continue;
          }

          for (const sample of provider.data || []) {
            if (!sample?.timestamp) continue;
            const sampleTs = new Date(sample.timestamp).getTime();
            if (!Number.isFinite(sampleTs) || sampleTs < dayStartMs) continue;

            const idx = Math.floor((sampleTs - dayStartMs) / bucketMs);
            if (idx < 0 || idx >= vramTotalBuckets) continue;

            const bucketTs = dayStartMs + idx * bucketMs;
            const isHour = idx % hourEvery === 0;
            const label = isHour
              ? new Date(bucketTs).toLocaleTimeString("en-GB", {
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: "UTC",
                })
              : "";

            const nextPoint = toVramChartPoint(sample, bucketTs, label);
            const currentPoint = series[idx];

            const samePoint =
              currentPoint &&
              !currentPoint._empty &&
              currentPoint.timestamp === nextPoint.timestamp &&
              currentPoint.used_vram_gb === nextPoint.used_vram_gb &&
              currentPoint.remaining_vram_gb === nextPoint.remaining_vram_gb &&
              currentPoint.models_loaded === nextPoint.models_loaded;

            if (samePoint) continue;

            if (next === prev) {
              next = { ...prev };
            }

            const updatedSeries = (next[provider.name] || series).slice();
            updatedSeries[idx] = nextPoint;
            next[provider.name] = updatedSeries;
            didUpdate = true;
          }
        }

        return next;
      });

      if (needsFullRebuild) return false;
      return didUpdate;
    },
    [toVramChartPoint, vramBucketSizeSec, vramTotalBuckets]
  );

  const chooseDynamicTargetBuckets = useCallback((spanMs: number) => {
    const hour = 60 * 60 * 1000;
    const day = 24 * hour;

    if (spanMs > 30 * day) return 90;
    if (spanMs > 7 * day) return 96;
    if (spanMs > day) return 108;
    return 120;
  }, []);

  const chooseDynamicBucketMs = useCallback(
    (spanMs: number) => {
      const minute = 60 * 1000;
      const hour = 60 * minute;
      const day = 24 * hour;
      const safeSpanMs = Math.max(spanMs, minute);
      const targetBuckets = chooseDynamicTargetBuckets(safeSpanMs);
      const rawBucketMs = Math.max(safeSpanMs / targetBuckets, minute);
      const niceCandidates = [
        minute,
        5 * minute,
        15 * minute,
        30 * minute,
        hour,
        3 * hour,
        6 * hour,
        12 * hour,
        day,
      ];

      return niceCandidates.reduce((best, candidate) =>
        Math.abs(candidate - rawBucketMs) < Math.abs(best - rawBucketMs)
          ? candidate
          : best
      );
    },
    [chooseDynamicTargetBuckets]
  );

  const aggregateEventsToVolumeSeries = useCallback(
    (
      events: TimelineEnqueueEvent[],
      startMs: number,
      endMs: number,
      bucketMs: number
    ): RequestEventStats["timeSeries"] => {
      const safeBucketMs = Math.max(bucketMs, 30 * 1000);
      const alignedStart = Math.floor(startMs / safeBucketMs) * safeBucketMs;
      const alignedEnd = Math.ceil(endMs / safeBucketMs) * safeBucketMs;
      const buckets = new Map<
        number,
        { cloud: number; local: number; total: number }
      >();

      for (let ts = alignedStart; ts <= alignedEnd; ts += safeBucketMs) {
        buckets.set(ts, { cloud: 0, local: 0, total: 0 });
      }

      for (const event of events) {
        const ts = Number(event.timestamp_ms);
        if (!Number.isFinite(ts) || ts < alignedStart || ts > alignedEnd)
          continue;
        const bucketTs = Math.floor(ts / safeBucketMs) * safeBucketMs;
        const bucket = buckets.get(bucketTs) || {
          cloud: 0,
          local: 0,
          total: 0,
        };
        if (event.is_cloud) bucket.cloud += 1;
        else bucket.local += 1;
        bucket.total += 1;
        buckets.set(bucketTs, bucket);
      }

      const rawSeries: RequestEventStats["timeSeries"] = [];
      for (const [timestamp, bucket] of buckets.entries()) {
        rawSeries.push({
          timestamp,
          label: "",
          cloud: bucket.cloud,
          local: bucket.local,
          total: bucket.total,
          avgRunSeconds: null,
          avgVram: null,
        });
      }

      rawSeries.sort((a, b) => a.timestamp - b.timestamp);
      return applyTimeSeriesLabels(
        rawSeries,
        new Date(alignedStart),
        new Date(alignedEnd)
      );
    },
    []
  );

  const replaceTimelineEvents = useCallback(
    (events: TimelineEnqueueEvent[]) => {
      const nextMap = new Map<string, TimelineEnqueueEvent>();
      for (const event of events || []) {
        if (!event?.request_id || !Number.isFinite(Number(event.timestamp_ms)))
          continue;
        nextMap.set(event.request_id, event);
      }
      const merged = Array.from(nextMap.values()).sort(
        (a, b) => a.timestamp_ms - b.timestamp_ms
      );
      setTimelineEvents(merged);
    },
    []
  );

  const replaceRawVramSeries = useCallback(
    (
      providers: Array<{ provider_id: number; name: string; data: Array<any> }>
    ) => {
      const next: { [url: string]: any[] } = {};
      for (const provider of providers || []) {
        const samples = (provider.data || [])
          .filter((sample) => sample?.timestamp)
          .sort(
            (a, b) =>
              new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
          );
        next[provider.name] = samples;
      }
      setVramRawDataByProvider(next);
    },
    []
  );

  const appendRawVramSeries = useCallback(
    (
      providers: Array<{ provider_id: number; name: string; data: Array<any> }>
    ) => {
      if (!providers || providers.length === 0) return;
      setVramRawDataByProvider((prev) => {
        let next = prev;
        for (const provider of providers) {
          const incoming = (provider.data || []).filter(
            (sample) => sample?.timestamp
          );
          if (!incoming.length) continue;
          const current = prev[provider.name] || [];
          const byKey = new Map<string, any>();
          for (const sample of current) {
            byKey.set(
              String(sample.snapshot_id ?? sample.timestamp ?? ""),
              sample
            );
          }
          for (const sample of incoming) {
            byKey.set(
              String(sample.snapshot_id ?? sample.timestamp ?? ""),
              sample
            );
          }
          const merged = Array.from(byKey.values()).sort(
            (a, b) =>
              new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
          );
          if (next === prev) next = { ...prev };
          next[provider.name] = merged;
        }
        return next;
      });
    },
    []
  );

  const [isVramLoading, setIsVramLoading] = useState(false);
  const wsTimelineConfig = useMemo(() => {
    const rangePeriod = customRange ? "custom" : timeWindow;
    const { startDate, endDate } = calculateDateRange(rangePeriod, customRange);
    const spanMs = Math.max(endDate.getTime() - startDate.getTime(), 60 * 1000);
    return {
      start: startDate.toISOString(),
      end: endDate.toISOString(),
      targetBuckets: chooseDynamicTargetBuckets(spanMs),
    };
  }, [chooseDynamicTargetBuckets, customRange, timeWindow]);

  const fetchVramStats = useCallback(
    async (options?: { silent?: boolean }) => {
      const silent = options?.silent ?? false;
      setVramError(null);

      // Only show spinner on first load, or when we actually detect a change.
      const shouldShowInitialSpinner =
        !silent && vramSignatureRef.current === null;
      if (shouldShowInitialSpinner) setIsVramLoading(true);

      // Calculate vramDayDate
      const now = new Date(nowMs);
      const vramDayDate = new Date(
        Date.UTC(
          now.getUTCFullYear(),
          now.getUTCMonth(),
          now.getUTCDate() - vramDayOffset
        )
      );
      const vramDayStr = vramDayDate.toISOString().slice(0, 10);

      try {
        const vramResponse = await fetch(
          `${API_BASE}/logosdb/get_ollama_vram_stats`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              logos_key: apiKey || "",
              Authorization: `Bearer ${apiKey}`,
            },
            body: JSON.stringify({
              day: vramDayStr,
            }),
          }
        );

        if (!vramResponse.ok) {
          throw new Error(`Backend returned ${vramResponse.status}`);
        }

        const vramData = await vramResponse.json();
        if (vramData?.error) {
          setVramError(vramData.error);
          return;
        }

        if (vramData.providers) {
          if (usePlotlyWeb) {
            replaceRawVramSeries(vramData.providers || []);
            setVramError(null);
            return;
          }

          const signature = buildVramSignature(vramData.providers || []);
          const isSame = signature === vramSignatureRef.current;

          if (isSame) {
            return; // no UI refresh needed
          }

          // New data: show spinner (only for non-silent/manual refresh) then apply.
          if (!silent && !shouldShowInitialSpinner) setIsVramLoading(true);

          vramSignatureRef.current = signature;
          processVramData(vramData.providers || [], vramDayDate);
        } else {
          setVramError("No VRAM data available.");
        }
      } catch (e) {
        console.error("[Statistics] Error fetching VRAM stats", e);
        setVramError(
          e instanceof Error ? e.message : "Failed to fetch VRAM stats."
        );
      } finally {
        if (!silent) setIsVramLoading(false);
      }
    },
    [
      apiKey,
      nowMs,
      processVramData,
      replaceRawVramSeries,
      usePlotlyWeb,
      vramDayOffset,
      vramSignatureRef,
    ]
  );

  const handleRequestsWsData = useCallback((payload: { requests?: any[] }) => {
    if (payload.requests) {
      const newRequests = payload.requests as RequestItem[];
      const currentIds = latestRequestsRef.current
        .map((r) => r.request_id)
        .join(",");
      const newIds = newRequests.map((r) => r.request_id).join(",");
      if (currentIds !== newIds) {
        LayoutAnimation.configureNext(LayoutAnimation.Presets.spring);
      }
      setLatestRequests(newRequests);
    }
  }, []);

  const handleVramWsInitV2 = useCallback(
    (payload: VramV2Payload) => {
      if (payload.error) {
        setVramError(payload.error);
        return;
      }
      if (payload.providers) {
        if (usePlotlyWeb) {
          replaceRawVramSeries(payload.providers);
        } else {
          const now = new Date();
          const dayAnchor = new Date(
            Date.UTC(
              now.getUTCFullYear(),
              now.getUTCMonth(),
              now.getUTCDate() - vramDayOffset
            )
          );
          processVramData(payload.providers, dayAnchor);
        }
        setVramError(null);
        setIsVramLoading(false);
      }
    },
    [processVramData, replaceRawVramSeries, usePlotlyWeb, vramDayOffset]
  );

  const handleVramWsDeltaV2 = useCallback(
    (payload: VramV2Payload) => {
      if (payload.error) {
        setVramError(payload.error);
        return;
      }
      if (!payload.providers || payload.providers.length === 0) return;

      if (usePlotlyWeb) {
        appendRawVramSeries(payload.providers);
        setVramError(null);
        setIsVramLoading(false);
        return;
      }

      const didIncrementalUpdate = appendVramDeltaSamples(payload.providers);
      if (!didIncrementalUpdate) {
        // If we missed state, fallback to the legacy HTTP snapshot fetch for recovery.
        fetchVramStats({ silent: true });
      }
      setVramError(null);
      setIsVramLoading(false);
    },
    [appendRawVramSeries, appendVramDeltaSamples, fetchVramStats, usePlotlyWeb]
  );

  const handleTimelineInitV2 = useCallback(
    (payload: TimelineInitPayload) => {
      if (payload.error) {
        setError(payload.error);
        setRefreshing(false);
        setHasResolvedStats(true);
        return;
      }
      if (!payload.stats) {
        setError("No statistics data available.");
        setRefreshing(false);
        setHasResolvedStats(true);
        return;
      }

      const rangeStart = payload.range?.start
        ? new Date(payload.range.start)
        : new Date(wsTimelineConfig.start);
      const rangeEnd = payload.range?.end
        ? new Date(payload.range.end)
        : new Date(wsTimelineConfig.end);
      const bucketSeconds = payload.bucketSeconds || 60;
      const bucketMs = bucketSeconds * 1000;
      const startMs = rangeStart.getTime();
      const endMs = rangeEnd.getTime();

      timelineRangeRef.current = { startMs, endMs, bucketMs };

      replaceTimelineEvents(payload.events || []);

      const labeled = applyTimeSeriesLabels(
        payload.stats.timeSeries || [],
        rangeStart,
        rangeEnd
      );
      setStats({ ...payload.stats, timeSeries: labeled });
      setError(null);
      setRefreshing(false);
      setHasResolvedStats(true);
    },
    [replaceTimelineEvents, wsTimelineConfig.start, wsTimelineConfig.end]
  );

  const { reconnect: reconnectWsV2 } = useStatsWebSocketV2({
    enabled: true,
    apiKey,
    vramDayOffset: usePlotlyWeb ? -1 : vramDayOffset,
    timeline: wsTimelineConfig,
    timelineDeltas: false,
    onVramInit: handleVramWsInitV2,
    onVramDelta: handleVramWsDeltaV2,
    onTimelineInit: handleTimelineInitV2,
    // Timeline live-updates disabled — initial snapshot only
    onTimelineDelta: () => {},
    onRequestsData: handleRequestsWsData,
  });

  // Keep "now" fresh so day rollover and live markers stay correct
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  // If we're on "Today", reset timeline at UTC midnight so the old day becomes "Yesterday".
  useEffect(() => {
    if (usePlotlyWeb) return;
    if (vramDayOffset !== 0) return;

    const now = new Date(nowMs);
    const utcDay = new Date(
      Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
    );
    const utcDayKey = utcDay.toISOString().slice(0, 10);

    if (!currentVramUtcDayRef.current) {
      currentVramUtcDayRef.current = utcDayKey;
      return;
    }

    if (currentVramUtcDayRef.current !== utcDayKey) {
      currentVramUtcDayRef.current = utcDayKey;
      vramSignatureRef.current = null;
      processVramData([], utcDay);
      reconnectWsV2();
    }
  }, [nowMs, processVramData, reconnectWsV2, usePlotlyWeb, vramDayOffset]);

  // onRefresh for pull-to-refresh refreshes everything
  const onRefresh = useCallback(() => {
    setRefreshing(true);
    reconnectWsV2();
  }, [reconnectWsV2]);

  const handleClearCustomRange = useCallback(() => {
    setCustomRange(null);
    setResetZoomCounter((c) => c + 1);
    setShowRangeBadge(false);
    rangeBadgeAnim.setValue(0);
  }, [rangeBadgeAnim]);

  // Show/hide badge with same vibe as the approve button, but 200ms
  useEffect(() => {
    const activeRange = customRange;
    if (activeRange) {
      setShowRangeBadge(true);
      Animated.timing(rangeBadgeAnim, {
        toValue: 1,
        duration: 200,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }).start();
    } else {
      Animated.timing(rangeBadgeAnim, {
        toValue: 0,
        duration: 200,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }).start(({ finished }) => {
        if (finished) setShowRangeBadge(false);
      });
    }
  }, [customRange, rangeBadgeAnim]);

  const { totalLineData, cloudLineData, localLineData } = useMemo(() => {
    if (!stats?.timeSeries)
      return { totalLineData: [], cloudLineData: [], localLineData: [] };

    const fallbackStart =
      stats.timeSeries[0]?.timestamp ?? Date.now() - 30 * 24 * 3600 * 1000;
    const fallbackEnd =
      stats.timeSeries[stats.timeSeries.length - 1]?.timestamp ?? Date.now();
    const rangeStartMs = customRange
      ? customRange.start.getTime()
      : (timelineRangeRef.current?.startMs ?? fallbackStart);
    const rangeEndMs = customRange
      ? customRange.end.getTime()
      : (timelineRangeRef.current?.endMs ?? fallbackEnd);

    if (
      !Number.isFinite(rangeStartMs) ||
      !Number.isFinite(rangeEndMs) ||
      rangeEndMs <= rangeStartMs
    ) {
      return { totalLineData: [], cloudLineData: [], localLineData: [] };
    }

    const bucketMs = chooseDynamicBucketMs(rangeEndMs - rangeStartMs);

    let series: RequestEventStats["timeSeries"] = [];

    if (timelineEvents.length > 0) {
      series = aggregateEventsToVolumeSeries(
        timelineEvents,
        rangeStartMs,
        rangeEndMs,
        bucketMs
      );
    } else {
      const alignedStart = Math.floor(rangeStartMs / bucketMs) * bucketMs;
      const alignedEnd = Math.ceil(rangeEndMs / bucketMs) * bucketMs;
      const buckets = new Map<
        number,
        { total: number; cloud: number; local: number }
      >();
      for (let ts = alignedStart; ts <= alignedEnd; ts += bucketMs) {
        buckets.set(ts, { total: 0, cloud: 0, local: 0 });
      }
      for (const point of stats.timeSeries) {
        if (point.timestamp < alignedStart || point.timestamp > alignedEnd)
          continue;
        const bucketTs = Math.floor(point.timestamp / bucketMs) * bucketMs;
        const current = buckets.get(bucketTs) || {
          total: 0,
          cloud: 0,
          local: 0,
        };
        current.total += point.total || 0;
        current.cloud += point.cloud || 0;
        current.local += point.local || 0;
        buckets.set(bucketTs, current);
      }
      series = applyTimeSeriesLabels(
        Array.from(buckets.entries())
          .map(([timestamp, value]) => ({
            timestamp,
            label: "",
            total: value.total,
            cloud: value.cloud,
            local: value.local,
            avgRunSeconds: null,
            avgVram: null,
          }))
          .sort((a, b) => a.timestamp - b.timestamp),
        new Date(alignedStart),
        new Date(alignedEnd)
      );
    }

    const total = series.map((point) => ({
      value: point.total || 0,
      dataPointText: "",
      timestamp: point.timestamp,
    }));
    const cloud = series.map((point) => ({
      value: point.cloud || 0,
      dataPointText: "",
      timestamp: point.timestamp,
    }));
    const local = series.map((point) => ({
      value: point.local || 0,
      dataPointText: "",
      timestamp: point.timestamp,
    }));

    return { totalLineData: total, cloudLineData: cloud, localLineData: local };
  }, [
    aggregateEventsToVolumeSeries,
    chooseDynamicBucketMs,
    customRange,
    stats,
    timelineEvents,
  ]);

  // ── Per-model time-series for the "By Model" view ──────────────────
  const modelSeriesMap = useMemo<
    Record<string, Array<{ value: number; timestamp: number }>>
  >(() => {
    const mts = stats?.modelTimeSeries;
    if (!mts?.length || !totalLineData.length) return {};

    // Get the bucket timestamps from the existing totalLineData so every model
    // series has identical x-coordinates (required for Plotly stacked bars).
    const bucketTimestamps = totalLineData.map((p) => p.timestamp);
    const bucketSet = new Set(bucketTimestamps);

    // Group raw backend entries by modelName, then by bucket timestamp
    const byModel: Record<string, Map<number, number>> = {};
    for (const entry of mts) {
      if (!byModel[entry.modelName]) {
        byModel[entry.modelName] = new Map();
      }
      // Aggregate into the nearest bucket that exists in our totalLineData
      // The backend bucket timestamps should align since we use the same bucket size
      const ts = entry.timestamp;
      if (bucketSet.has(ts)) {
        const m = byModel[entry.modelName];
        m.set(ts, (m.get(ts) || 0) + entry.count);
      } else {
        // Find the closest bucket (backend may have slight bucket alignment differences)
        let closest = bucketTimestamps[0];
        let minDist = Math.abs(ts - closest);
        for (const bt of bucketTimestamps) {
          const dist = Math.abs(ts - bt);
          if (dist < minDist) {
            minDist = dist;
            closest = bt;
          }
        }
        const m = byModel[entry.modelName];
        m.set(closest, (m.get(closest) || 0) + entry.count);
      }
    }

    // Build series with a point for every bucket (0 if no data)
    const result: Record<
      string,
      Array<{ value: number; timestamp: number }>
    > = {};
    for (const [modelName, bucketMap] of Object.entries(byModel)) {
      result[modelName] = bucketTimestamps.map((ts) => ({
        value: bucketMap.get(ts) || 0,
        timestamp: ts,
      }));
    }
    return result;
  }, [stats?.modelTimeSeries, totalLineData]);

  /** Unified model color palette — shared between bar chart and pie chart */
  const modelColors = useMemo<Record<string, string>>(() => {
    const MODEL_PALETTE = [
      "#F29C6E", // orange
      "#3BE9DE", // cyan
      "#9D4EDD", // purple
      "#06FFA5", // green
      "#EC4899", // pink
      "#6366F1", // indigo
      "#F59E0B", // amber
      "#14B8A6", // teal
    ];
    // Assign by modelBreakdown order (most requests first) for consistency
    const breakdown = stats?.modelBreakdown ?? [];
    const map: Record<string, string> = {};
    breakdown.forEach((m, idx) => {
      map[m.modelName] = MODEL_PALETTE[idx % MODEL_PALETTE.length];
    });
    // Also cover any names from modelSeriesMap not in breakdown
    Object.keys(modelSeriesMap).forEach((name) => {
      if (!map[name]) {
        map[name] =
          MODEL_PALETTE[Object.keys(map).length % MODEL_PALETTE.length];
      }
    });
    return map;
  }, [modelSeriesMap, stats?.modelBreakdown]);

  const providerPieData = useMemo(() => {
    if (!stats) return [];
    return [
      {
        value: stats.totals.cloudRequests,
        color: CHART_PALETTE.cloud,
        text: "Cloud",
      },
      {
        value: stats.totals.localRequests,
        color: CHART_PALETTE.local,
        text: "Local",
      },
    ].filter((d) => d.value > 0);
  }, [stats]);

  const modelPieData = useMemo(() => {
    return (stats?.modelBreakdown ?? []).slice(0, 5).map((m) => ({
      value: m.requestCount,
      color: modelColors[m.modelName] || "#94A3B8",
      text: m.modelName,
    }));
  }, [stats, modelColors]);

  const showStatsSkeleton = !hasResolvedStats && !stats && !error;

  return (
    <ScrollView
      className="w-full"
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
      }
      showsVerticalScrollIndicator={false}
    >
      <VStack className="w-full space-y-3">
        <Text
          size="2xl"
          className="text-center font-bold text-black dark:text-white"
        >
          Statistics
        </Text>

        {showStatsSkeleton ? (
          <StatisticsPageSkeleton />
        ) : stats ? (
          <VStack space="md">
            {/* Latest Requests + VRAM Utilization */}
            <View className="w-full flex-col gap-3 xl:flex-row xl:items-start xl:gap-6">
              <View className="w-full xl:flex-1">
                <RequestStack requests={latestRequests} />
              </View>
              <View className="mx-4 hidden w-px self-stretch bg-outline-200 xl:flex" />
              <View className="w-full xl:flex-1">
                <ChartCard
                  title="VRAM Utilization"
                  subtitle="Latest snapshot per Ollama provider"
                >
                  {(width) => {
                    if (isVramLoading) {
                      return (
                        <View
                          style={{
                            height: 320,
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                        >
                          <ActivityIndicator size="large" color="#006DFF" />
                        </View>
                      );
                    }

                    if (vramError) {
                      return <EmptyState message={vramError} />;
                    }

                    if (!vramProviders.length) {
                      return (
                        <EmptyState message="No VRAM snapshot data available." />
                      );
                    }

                    if (!selectedVramProvider || !vramPieData.length) {
                      return (
                        <EmptyState message="No utilization data for the selected provider." />
                      );
                    }

                    return (
                      <VStack space="md" className="w-full">
                        <View className="w-full">
                          <Select
                            selectedValue={selectedVramProvider}
                            onValueChange={(val) =>
                              setSelectedVramProvider(val || null)
                            }
                          >
                            <SelectTrigger className="rounded-full border border-outline-200 bg-background-50 px-3 py-2">
                              <SelectInput
                                placeholder="Select provider"
                                value={selectedVramProvider ?? ""}
                                className="text-typography-900"
                              />
                            </SelectTrigger>
                            <SelectPortal>
                              <SelectBackdrop />
                              <SelectContent className="border border-outline-200 bg-background-50">
                                {vramProviders.map((provider) => (
                                  <SelectItem
                                    key={provider}
                                    label={provider}
                                    value={provider}
                                  />
                                ))}
                              </SelectContent>
                            </SelectPortal>
                          </Select>
                        </View>

                        <View className="h-px w-full bg-outline-200" />

                        {usePlotlyWeb ? (
                          <View style={{ alignItems: "center" }}>
                            <PlotlyPieChart
                              data={vramPieData}
                              width={width}
                              height={260}
                              pieScale={0.85}
                              legendPosition="right"
                              centerText={{
                                top: "Free",
                                middle: `${vramSummary.freePct}%`,
                                bottom: `of ${vramSummary.totalGb.toFixed(1)} GB`,
                              }}
                            />
                          </View>
                        ) : (
                          (() => {
                            const { radius, innerRadius } = getPieSizing(
                              width,
                              0.85
                            );
                            return (
                              <View style={{ alignItems: "center" }}>
                                <View
                                  style={{
                                    alignItems: "center",
                                    justifyContent: "center",
                                  }}
                                >
                                  <View
                                    pointerEvents="none"
                                    className="absolute rounded-full bg-secondary-200"
                                    style={{
                                      width: innerRadius * 2,
                                      height: innerRadius * 2,
                                    }}
                                  />
                                  <PieChart
                                    data={vramPieData}
                                    donut
                                    innerRadius={innerRadius}
                                    radius={radius}
                                    isAnimated={false}
                                    focusOnPress
                                    toggleFocusOnPress
                                    centerLabelComponent={() => (
                                      <View className="items-center">
                                        <Text className="text-xs text-typography-500 dark:text-typography-400">
                                          Free
                                        </Text>
                                        <Text className="text-xl font-semibold text-typography-900 dark:text-typography-50">
                                          {vramSummary.freePct}%
                                        </Text>
                                        <Text className="text-xs text-typography-500 dark:text-typography-400">
                                          of {vramSummary.totalGb.toFixed(1)} GB
                                        </Text>
                                      </View>
                                    )}
                                  />
                                </View>

                                <VStack className="mt-4 space-y-1">
                                  {vramPieData.map((d, i) => (
                                    <HStack
                                      key={i}
                                      space="xs"
                                      className="items-center"
                                    >
                                      <View
                                        style={{
                                          width: 10,
                                          height: 10,
                                          borderRadius: 5,
                                          backgroundColor: d.color,
                                        }}
                                      />
                                      <Text className="text-xs text-typography-700">
                                        {d.text}: {d.value.toFixed(1)} GB
                                      </Text>
                                    </HStack>
                                  ))}
                                </VStack>
                              </View>
                            );
                          })()
                        )}
                      </VStack>
                    );
                  }}
                </ChartCard>
              </View>
            </View>

            <View className="mt-5 h-[1px] w-full bg-outline-200" />

            {/* Controls Container */}
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                marginTop: 8,
                marginBottom: 8,
                paddingHorizontal: 12,
                gap: 10,
              }}
            >
              {showRangeBadge && (
                <Animated.View
                  style={{
                    opacity: rangeBadgeAnim,
                    transform: [
                      {
                        scale: rangeBadgeAnim.interpolate({
                          inputRange: [0, 1],
                          outputRange: [0.95, 1],
                        }),
                      },
                    ],
                  }}
                >
                  <View className="flex-row items-center rounded-full border border-outline-200 bg-background-50 py-1 pl-4 pr-1">
                    <Text className="mr-3 text-sm font-medium text-typography-700">
                      {customRange ? formatRangeLabel(customRange) : ""}
                    </Text>
                    <Button
                      size="xs"
                      variant="link"
                      action="negative"
                      onPress={handleClearCustomRange}
                      className="h-6 w-6 items-center justify-center rounded-full border border-outline-200 bg-red-50 p-0 dark:bg-red-950"
                      accessibilityLabel="Clear selected range"
                    >
                      <ButtonIcon as={CloseIcon} size="xs" />
                    </Button>
                  </View>
                </Animated.View>
              )}
            </View>

            {/* Main Volume Chart Card */}
            {!stats.timeSeries?.length ? (
              <ChartCard
                title="Request Volume"
                subtitle="Requests volume aggregated into dynamic buckets based on the selected time range"
                className="mb-2 mt-0"
              >
                {() => (
                  <EmptyState message="No request volume data in the selected range." />
                )}
              </ChartCard>
            ) : (
              <ChartCard
                title="Request Volume"
                subtitle="Requests volume aggregated into dynamic buckets based on the selected time range"
                className="mb-2 mt-0"
              >
                {(width) => (
                  <View>
                    {usePlotlyWeb ? (
                      <PlotlyRequestVolumeChart
                        width={width}
                        totalLineData={totalLineData}
                        cloudLineData={cloudLineData}
                        localLineData={localLineData}
                        modelSeriesMap={modelSeriesMap}
                        modelBreakdown={stats?.modelBreakdown}
                        modelColors={modelColors}
                        onZoom={setCustomRange}
                        resetZoomTrigger={resetZoomCounter}
                        colors={{
                          total: CHART_PALETTE.total,
                          cloud: CHART_PALETTE.cloud,
                          local: CHART_PALETTE.local,
                        }}
                      />
                    ) : (
                      <InteractiveZoomableChart
                        width={width}
                        totalLineData={totalLineData}
                        cloudLineData={cloudLineData}
                        localLineData={localLineData}
                        onZoom={setCustomRange}
                        colors={{
                          total: CHART_PALETTE.total,
                          cloud: CHART_PALETTE.cloud,
                          local: CHART_PALETTE.local,
                        }}
                      />
                    )}
                  </View>
                )}
              </ChartCard>
            )}

            <HStack space="sm" className="w-full">
              <View style={{ flex: 1 }}>
                <ChartCard title="Request Type" className="flex-1">
                  {(width) => {
                    if (!providerPieData.length) {
                      return <EmptyState message="No requests in range." />;
                    }
                    if (usePlotlyWeb) {
                      const total = providerPieData.reduce(
                        (s, d) => s + d.value,
                        0
                      );
                      return (
                        <View style={{ alignItems: "center" }}>
                          <PlotlyPieChart
                            data={providerPieData}
                            width={width}
                            height={260}
                            legendPosition="right"
                            centerText={{
                              middle: `${total}`,
                              bottom: "requests",
                            }}
                          />
                        </View>
                      );
                    }
                    const { radius, innerRadius } = getPieSizing(width);
                    return (
                      <View style={{ alignItems: "center" }}>
                        <View
                          style={{
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                        >
                          <View
                            pointerEvents="none"
                            className="absolute rounded-full bg-secondary-200"
                            style={{
                              width: innerRadius * 2,
                              height: innerRadius * 2,
                            }}
                          />
                          <PieChart
                            data={providerPieData}
                            donut
                            innerRadius={innerRadius}
                            radius={radius}
                            showText={false}
                            textColor="white"
                            textSize={12}
                            showValuesAsLabels
                            isAnimated={false}
                            focusOnPress
                            toggleFocusOnPress
                          />
                        </View>
                        <VStack className="mt-4 space-y-1">
                          {providerPieData.map((d, i) => (
                            <HStack key={i} space="xs" className="items-center">
                              <View
                                style={{
                                  width: 10,
                                  height: 10,
                                  borderRadius: 5,
                                  backgroundColor: d.color,
                                }}
                              />
                              <Text className="text-xs text-typography-700">
                                {d.text}: {d.value}
                              </Text>
                            </HStack>
                          ))}
                        </VStack>
                      </View>
                    );
                  }}
                </ChartCard>
              </View>
              <View style={{ flex: 1 }}>
                <ChartCard title="Model Share" className="flex-1">
                  {(width) => {
                    if (!modelPieData.length) {
                      return <EmptyState message="No requests in range." />;
                    }
                    if (usePlotlyWeb) {
                      const total = modelPieData.reduce(
                        (s, d) => s + d.value,
                        0
                      );
                      return (
                        <View style={{ alignItems: "center" }}>
                          <PlotlyPieChart
                            data={modelPieData}
                            width={width}
                            height={260}
                            legendPosition="right"
                            centerText={{
                              middle: `${total}`,
                              bottom: "requests",
                            }}
                          />
                        </View>
                      );
                    }
                    const { radius, innerRadius } = getPieSizing(width);
                    return (
                      <View style={{ alignItems: "center" }}>
                        <View
                          style={{
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                        >
                          <View
                            pointerEvents="none"
                            className="absolute rounded-full bg-secondary-200"
                            style={{
                              width: innerRadius * 2,
                              height: innerRadius * 2,
                            }}
                          />
                          <PieChart
                            data={modelPieData}
                            donut
                            innerRadius={innerRadius}
                            radius={radius}
                            showText={false}
                            isAnimated={false}
                            focusOnPress
                            toggleFocusOnPress
                          />
                        </View>
                        <VStack className="mt-4 space-y-1">
                          {modelPieData.map((d, i) => (
                            <HStack key={i} space="xs" className="items-center">
                              <View
                                style={{
                                  width: 10,
                                  height: 10,
                                  borderRadius: 5,
                                  backgroundColor: d.color,
                                }}
                              />
                              <Text className="text-xs text-typography-700">
                                {d.text}
                              </Text>
                            </HStack>
                          ))}
                        </VStack>
                      </View>
                    );
                  }}
                </ChartCard>
              </View>
            </HStack>

            <View className="my-8 h-[1px] w-full bg-outline-200" />

            <ChartCard title="VRAM Remaining" subtitle="Per Ollama-Provider">
              {(width) =>
                usePlotlyWeb ? (
                  <PlotlyVramChart
                    width={width}
                    vramDayOffset={vramDayOffset}
                    setVramDayOffset={setVramDayOffset}
                    fetchVramStats={fetchVramStats}
                    isVramLoading={isVramLoading}
                    vramError={vramError}
                    vramDataByProvider={vramRawDataByProvider}
                    vramBaseline={vramBaseline}
                    vramBucketSizeSec={vramBucketSizeSec}
                    vramTotalBuckets={vramTotalBuckets}
                    getProviderColor={getProviderColor}
                    nowMs={nowMs}
                  />
                ) : (
                  <VramChart
                    width={width}
                    vramDayOffset={vramDayOffset}
                    setVramDayOffset={setVramDayOffset}
                    fetchVramStats={fetchVramStats}
                    isVramLoading={isVramLoading}
                    vramError={vramError}
                    vramDataByProvider={vramDataByProvider}
                    vramBaseline={vramBaseline}
                    vramBucketSizeSec={vramBucketSizeSec}
                    vramTotalBuckets={vramTotalBuckets}
                    getProviderColor={getProviderColor}
                    nowMs={nowMs}
                  />
                )
              }
            </ChartCard>
          </VStack>
        ) : (
          <VStack className="items-center gap-4 py-8">
            <Text className="text-center text-red-500">
              {error || "Unable to load statistics."}
            </Text>
            <Button
              size="sm"
              variant="outline"
              action="primary"
              onPress={onRefresh}
            >
              <Text>Retry</Text>
            </Button>
          </VStack>
        )}
      </VStack>
    </ScrollView>
  );
}
