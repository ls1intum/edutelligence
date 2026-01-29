import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Animated,
  Easing,
  LayoutAnimation,
  PanResponder,
  Platform,
  RefreshControl,
  ScrollView,
  UIManager,
  View,
} from "react-native";
import { PieChart } from "react-native-gifted-charts";

import { useAuth } from "@/components/auth-shell";
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonIcon } from "@/components/ui/button";
import {
  Select,
  SelectBackdrop,
  SelectContent,
  SelectInput,
  SelectItem,
  SelectPortal,
  SelectTrigger,
} from "@/components/ui/select";

import { CheckIcon, CloseIcon } from "@/components/ui/icon";
import { RotateCw } from "lucide-react-native";


import type {
  RequestEventRow,
  RequestEventResponse,
  RequestEventStats,
} from "@/components/statistics/types";
import ChartCard from "@/components/statistics/chart-card";
import EmptyState from "@/components/statistics/empty-state";
import InteractiveZoomableChart from "@/components/statistics/interactive-zoomable-chart";
import VramChart from "@/components/statistics/vram-chart";
import {
  MOCK_RESPONSE,
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
import { Skeleton } from "@/components/ui/skeleton";

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

const getPieSizing = (width: number) => {
  const size = Math.min(width, 260);
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

export default function Statistics() {
  const { apiKey } = useAuth();

  // State
  // Note: timeWindow is currently hardcoded to 30d. If you need to make this dynamic, convert to useState.
  const timeWindow: "30d" = "30d";
  const [customRange, setCustomRange] = useState<{
    start: Date;
    end: Date;
  } | null>(null);
  const [showRangeBadge, setShowRangeBadge] = useState(false);
  const rangeBadgeAnim = useRef(new Animated.Value(0)).current;

  // Recent Requests Stack
  const [latestRequests, setLatestRequests] = useState<RequestItem[]>([]);
  const [latestRequestsError, setLatestRequestsError] = useState<string | null>(
    null
  );
  const latestRequestsRef = useRef(latestRequests);
  useEffect(() => {
    latestRequestsRef.current = latestRequests;
  }, [latestRequests]);

  // Data
  const [stats, setStats] = useState<RequestEventStats | null>(null);
  const [allRows, setAllRows] = useState<RequestEventRow[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [chartsRefreshing, setChartsRefreshing] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [vramError, setVramError] = useState<string | null>(null);
  const [isUsingDemoData, setIsUsingDemoData] = useState(false);
  const [nowRef] = useState<number>(Date.now()); // Stable hydration
  const [vramDayOffset, setVramDayOffset] = useState(0); // 0 = today, 1 = yesterday, etc.
  const [vramDataByProvider, setVramDataByProvider] = useState<{
    [url: string]: Array<VramSeriesPoint>;
  }>({});
  const [selectedVramProvider, setSelectedVramProvider] = useState<string | null>(null);
  const [vramBaseline, setVramBaseline] = useState<any[]>([]);
  const [vramBucketSizeSec, setVramBucketSizeSec] = useState(10);
  const [vramTotalBuckets, setVramTotalBuckets] = useState(8640);
  const vramSignatureRef = useRef<string | null>(null);
  const initialFetchDone = useRef(false);

  // Compute filtered rows
  const filteredRows = useMemo(() => {
    if (!allRows.length) return [];

    let rows = [...allRows];

    if (customRange) {
      rows = rows.filter((r) => {
        if (!r.enqueue_ts) return false;
        const t = new Date(r.enqueue_ts);
        return t >= customRange.start && t <= customRange.end;
      });
    } else {
      // Default to 30-day window
      const now = new Date(nowRef);
      const cutoff = new Date(nowRef);
      if (timeWindow === "30d") cutoff.setDate(now.getDate() - 30);
      else if (timeWindow === "7d") cutoff.setDate(now.getDate() - 7);
      else if (timeWindow === "24h") cutoff.setHours(now.getHours() - 24);
      rows = rows.filter(
        (r) => r.enqueue_ts && new Date(r.enqueue_ts) >= cutoff
      );
    }
    return rows;
  }, [allRows, timeWindow, customRange, nowRef]);

  const vramProviders = useMemo(
    () => Object.keys(vramDataByProvider).sort(),
    [vramDataByProvider]
  );

  useEffect(() => {
    if (!vramProviders.length) {
      setSelectedVramProvider(null);
      return;
    }
    if (!selectedVramProvider || !vramProviders.includes(selectedVramProvider)) {
      setSelectedVramProvider(vramProviders[0]);
    }
  }, [vramProviders, selectedVramProvider]);

  const latestVramSample = useMemo(() => {
    if (!selectedVramProvider) return null;
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
  }, [selectedVramProvider, vramDataByProvider]);

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

    const modeledUsed = modelSlices.reduce((sum, slice) => sum + slice.value, 0);
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
            .join(", ")}${models.length > 3 ? ` +${models.length - 3} more` : ""}`
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

  // Recalculate stats whenever filteredRows changes
  const computeStats = useCallback(
    (rows: RequestEventRow[]): RequestEventStats => {
      const toDate = (v: string | null) => (v ? new Date(v) : null);
      const avg = (arr: number[]) =>
        arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null;

      const allTimes: Date[] = [];
      rows.forEach((r) => {
        ["request_complete_ts", "scheduled_ts", "enqueue_ts"].forEach((k) => {
          const val = (r as any)[k] as string | null;
          if (val) {
            const d = new Date(val);
            if (!isNaN(d.getTime())) allTimes.push(d);
          }
        });
      });
      const lastEvent = allTimes.length
        ? new Date(Math.max(...allTimes.map((d) => d.getTime())))
        : null;

      const statusCounts: Record<string, number> = {};
      rows.forEach((r) => {
        const key = (r.result_status || "unknown").toLowerCase();
        statusCounts[key] = (statusCounts[key] || 0) + 1;
      });

      const totals = {
        requests: rows.length,
        cloudRequests: rows.filter((r) => r.provider_id === 2).length,
        localRequests: rows.filter((r) => r.provider_id !== 2).length,
        coldStarts: rows.filter((r) => r.cold_start === true).length,
        warmStarts: rows.filter(
          (r) => r.cold_start === false || r.cold_start === null
        ).length,
        avgQueueSeconds: null as number | null,
        avgRunSeconds: null as number | null,
      };

      const queueDurations: number[] = [];
      const runDurations: number[] = [];
      rows.forEach((r) => {
        const enq = toDate(r.enqueue_ts);
        const sched = toDate(r.scheduled_ts);
        const done = toDate(r.request_complete_ts);
        if (enq && sched)
          queueDurations.push((sched.getTime() - enq.getTime()) / 1000);
        if (sched && done)
          runDurations.push((done.getTime() - sched.getTime()) / 1000);
      });
      totals.avgQueueSeconds = avg(queueDurations);
      totals.avgRunSeconds = avg(runDurations);

      const modelMap: Record<number, RequestEventRow[]> = {};
      rows.forEach((r) => {
        const id = r.model_id ?? -1;
        if (!modelMap[id]) modelMap[id] = [];
        modelMap[id].push(r);
      });
      const modelBreakdown = Object.entries(modelMap)
        .map(([id, list]) => {
          const rqDur: number[] = [];
          const runDur2: number[] = [];
          list.forEach((r) => {
            const enq = toDate(r.enqueue_ts);
            const sched = toDate(r.scheduled_ts);
            const done = toDate(r.request_complete_ts);
            if (enq && sched)
              rqDur.push((sched.getTime() - enq.getTime()) / 1000);
            if (sched && done)
              runDur2.push((done.getTime() - sched.getTime()) / 1000);
          });
          const errors = list.filter(
            (r) =>
              (r.result_status && r.result_status !== "success") ||
              (r.error_message && r.error_message.length)
          ).length;
          return {
            modelId: Number(id),
            modelName: `Model ${id}`,
            providerName: list[0]?.provider_id
              ? `Provider ${list[0].provider_id}`
              : "Provider",
            requestCount: list.length,
            avgQueueSeconds: avg(rqDur),
            avgRunSeconds: avg(runDur2),
            coldStarts: list.filter((r) => r.cold_start === true).length,
            warmStarts: list.filter(
              (r) => r.cold_start === false || r.cold_start === null
            ).length,
            errorCount: errors,
          };
        })
        .sort((a, b) => b.requestCount - a.requestCount);

      // Dynamic Bucketing
      const now = nowRef;

      // Determine the full time range of the *current view* (timeWindow or customRange)
      // We want ~100-150 data points for good granularity
      let startTs = now;
      let endTs = now;
      if (customRange) {
        startTs = customRange.start.getTime();
        endTs = customRange.end.getTime();
      } else {
        if (timeWindow === "30d") startTs = now - 30 * 24 * 3600 * 1000;
        else if (timeWindow === "7d") startTs = now - 7 * 24 * 3600 * 1000;
        else if (timeWindow === "24h") startTs = now - 24 * 3600 * 1000;
      }
      const durationMs = endTs - startTs;
      const targetPoints = 120; // Target resolution
      let rawBucketMs = durationMs / targetPoints;

      // Snap to nice intervals
      const niceIntervals = [
        60 * 1000, // 1m
        5 * 60 * 1000, // 5m
        15 * 60 * 1000, // 15m
        60 * 60 * 1000, // 1h
        4 * 60 * 60 * 1000, // 4h
        12 * 60 * 60 * 1000, // 12h
        24 * 60 * 60 * 1000, // 1d
      ];
      // Find closest nice interval, default to raw if nothing close (or just use raw for max precision?)
      // Let's use raw for max precision so it fits exactly, or just snap to nearest larger nice one?
      // User wants "visible spikes". Strict 120 points is good.
      // But buckets align better if they are round numbers.
      let bucketMs = niceIntervals.reduce((prev, curr) =>
        Math.abs(curr - rawBucketMs) < Math.abs(prev - rawBucketMs)
          ? curr
          : prev
      );
      // Ensure we don't go too small or too large if outside bounds
      if (rawBucketMs < 60 * 1000) bucketMs = 60 * 1000;

      const bucketMap: Record<
        number,
        { cloud: number; local: number; run: number[]; vram: number[] }
      > = {};

      rows.forEach((r) => {
        const ts = r.scheduled_ts
          ? new Date(r.scheduled_ts).getTime()
          : r.enqueue_ts
            ? new Date(r.enqueue_ts).getTime()
            : 0;
        if (!ts) return;

        const bucket = Math.floor(ts / bucketMs) * bucketMs;
        if (!bucketMap[bucket])
          bucketMap[bucket] = { cloud: 0, local: 0, run: [], vram: [] };

        const isCloud = r.provider_id === 2;
        if (isCloud) bucketMap[bucket].cloud++;
        else bucketMap[bucket].local++;

        const done = toDate(r.request_complete_ts);
        const start = toDate(r.scheduled_ts);
        if (done && start)
          bucketMap[bucket].run.push((done.getTime() - start.getTime()) / 1000);
        if (r.available_vram_mb)
          bucketMap[bucket].vram.push(r.available_vram_mb);
      });

      const timeSeries = Object.entries(bucketMap)
        .map(([tsStr, data]) => {
          const ts = Number(tsStr);
          // Labeling logic happens later to avoid clutter
          return {
            timestamp: ts,
            label: "", // Placeholder, populated below
            cloud: data.cloud,
            local: data.local,
            total: data.cloud + data.local,
            avgRunSeconds: avg(data.run),
            avgVram: avg(data.vram),
          };
        })
        .sort((a, b) => a.timestamp - b.timestamp);

      // Post-process labels: ~10 labels max
      const labelStep = Math.max(1, Math.ceil(timeSeries.length / 5)); // halve the label count
      let lastLabel = "";

      timeSeries.forEach((pt, idx) => {
        if (idx % labelStep === 0) {
          const date = new Date(pt.timestamp);
          let newLabel = "";
          // Smart formatting
          if (durationMs < 24 * 3600 * 1000) {
            // < 24h: Show time
            newLabel = date.toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            });
          } else if (durationMs < 7 * 24 * 3600 * 1000) {
            // < 7d: Show Day + Time or Date + Time
            // Showing MM/DD HH:mm for compactness
            newLabel = `${
              date.getMonth() + 1
            }/${date.getDate()} ${date.getHours()}h`;
          } else {
            // > 7d: Show Date
            newLabel = `${date.getDate()}/${date.getMonth() + 1}`;
          }

          if (newLabel !== lastLabel) {
            pt.label = newLabel;
            lastLabel = newLabel;
          }
        }
      });

      const enqueueDepths = rows
        .map((r) => r.queue_depth_at_enqueue)
        .filter((v): v is number => typeof v === "number");
      const scheduleDepths = rows
        .map((r) => r.queue_depth_at_schedule)
        .filter((v): v is number => typeof v === "number");
      const percentile = (arr: number[], p: number) => {
        if (!arr.length) return null;
        const sorted = [...arr].sort((a, b) => a - b);
        const idx = (p / 100) * (sorted.length - 1);
        const lo = Math.floor(idx);
        const hi = Math.ceil(idx);
        if (lo === hi) return sorted[lo];
        return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
      };
      const queueDepth = {
        avgEnqueueDepth: avg(enqueueDepths),
        avgScheduleDepth: avg(scheduleDepths),
        p95EnqueueDepth: percentile(enqueueDepths, 95),
        p95ScheduleDepth: percentile(scheduleDepths, 95),
      };

      const runtimeByColdStart = (["cold", "warm"] as const).map((type) => {
        const isCold = type === "cold";
        const subset = rows.filter((r) => (r.cold_start ?? false) === isCold);
        const runDurCold: number[] = [];
        subset.forEach((r) => {
          const sched = toDate(r.scheduled_ts);
          const done = toDate(r.request_complete_ts);
          if (sched && done)
            runDurCold.push((done.getTime() - sched.getTime()) / 1000);
        });
        return {
          type: isCold ? "cold" : "warm",
          avgRunSeconds: avg(runDurCold),
          count: subset.length,
        } as {
          type: "cold" | "warm";
          avgRunSeconds: number | null;
          count: number;
        };
      });

      return {
        lastEventTs: lastEvent ? lastEvent.toISOString() : null,
        totals,
        statusCounts,
        modelBreakdown,
        timeSeries,
        queueDepth,
        runtimeByColdStart,
      };
    },
    [timeWindow, customRange, nowRef]
  );

  // Recompute stats locally only in demo/fallback mode
  useEffect(() => {
    if (!isUsingDemoData) return;
    setStats(computeStats(filteredRows));
  }, [isUsingDemoData, filteredRows, computeStats]);

  // Helper functions for VRAM data

  const resolveVramBucketSize = useCallback(() => {
    // Keep demo-mode lighter on web to avoid massive renders/refresh traversals
    if (Platform.OS === "web" && isUsingDemoData) return 60; // 1m buckets in demo on web
    return 10; // 10s buckets otherwise
  }, [isUsingDemoData]);

  const processVramData = useCallback(
    (
      providers: Array<{ provider_id: number; name: string; data: Array<any> }>,
      period: string,
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

          // User wants "Remaining Memory" logic
          const raw = b.raw;
          const usedBytes =
            typeof raw.vram_bytes === "number"
              ? raw.vram_bytes
              : (raw.used_vram_mb || raw.vram_mb || 0) * BYTES_PER_MIB;
          const configuredTotalBytes =
            (raw.total_vram_mb || 0) * BYTES_PER_MIB;
          const remainingBytes =
            raw.remaining_vram_mb != null
              ? raw.remaining_vram_mb * BYTES_PER_MIB
              : Math.max(0, configuredTotalBytes - usedBytes);
          const remainingGb = toDecimalGb(remainingBytes);
          const usedGb = toDecimalGb(usedBytes);
          const totalGb = toDecimalGb(usedBytes + remainingBytes);
          const loadedModels = (raw.loaded_models || [])
            .map((m: any) => {
              const sizeBytes =
                typeof m.size_vram === "number"
                  ? m.size_vram
                  : typeof m.size_vram_mb === "number"
                    ? m.size_vram_mb * BYTES_PER_MIB
                    : 0;
              const sizeGb = toDecimalGb(sizeBytes);
              return {
                name: m.name ?? m.model ?? "model",
                size_gb: sizeGb,
              };
            })
            .filter((m: any) => m.size_gb > 0);
          const loadedModelNames = loadedModels.map((m: any) => m.name);

          return {
            value: remainingGb, // Chart Remaining VRAM
            label: t.label, // Time label for hourly markers
            timestamp: t.timestamp,
            used_vram_gb: usedGb,
            remaining_vram_gb: remainingGb,
            total_vram_gb: totalGb,
            models_loaded: raw.models_loaded ?? 0,
            loaded_model_names: loadedModelNames,
            loaded_models: loadedModels,
            // Ensure we have properties needed for render
            hideDataPoint: false, // Show data points
            dataPointRadius: 2,
            _empty: false,
          };
        });
        processed[p.name] = lineData;
      });

      // Provide a baseline for the x-axis labels and total width.
      const baseline = timeline.map((t) => ({
        value: 0,
        label: t.label,
        _isBaseline: true,
      }));

      setVramBucketSizeSec(bucketSec);
      setVramTotalBuckets(TOTAL_POINTS);
      setVramBaseline(baseline);
      setVramDataByProvider(processed);
    },
    [resolveVramBucketSize]
  );

  // Mock VRAM data for troubleshooting when API fails
  const buildMockVramProviders = useCallback((day: Date) => {
    const base = new Date(
      Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate())
    );
    const points = 100;
    const spanMs = 24 * 3600 * 1000;
    const samples = Array.from({ length: points }).map((_, i) => {
      const ts = new Date(
        base.getTime() + (spanMs * i) / (points - 1)
      ).toISOString();
      // oscillate between 6 GB and 24 GB free with slight noise
      const freeMb =
        6000 + Math.abs(Math.sin(i / 8)) * 18000 + Math.random() * 800;
      const usedMb = Math.max(0, 32000 - freeMb);
      return {
        timestamp: ts,
        remaining_vram_mb: Math.round(freeMb),
        vram_mb: Math.round(usedMb),
        total_vram_mb: 30518,
        models_loaded: Math.floor(Math.random() * 4),
        loaded_models: [],
      };
    });
    return [
      {
        provider_id: 0,
        name: "Mock Provider",
        data: samples,
      },
    ];
  }, []);

  const [isVramLoading, setIsVramLoading] = useState(false);

  const fetchStats = useCallback(
    async () => {
      // Note: apiKey check skipped to allow demo mode or immediate mock fallback
      setRefreshing(true);
      setError(null);
      setIsUsingDemoData(false);

      const rangePeriod = customRange ? "custom" : timeWindow;
      const { startDate, endDate } = calculateDateRange(
        rangePeriod,
        customRange
      );

      // VRAM day calculation moved to fetchVramStats specifically,
      // but we can keep 'now' ref if needed for other things.

      try {
        let data: RequestEventResponse | null = null;
        let usedMock = false;

        // Fetch aggregated request events
        // Note: We used to fetch latest requests here, but now it's polled separately
        try {
          const response = await fetch(
            `${API_BASE}/logosdb/request_event_stats`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                logos_key: apiKey || "",
                Authorization: `Bearer ${apiKey}`,
              },
              body: JSON.stringify({
                logos_key: apiKey,
                start_date: startDate.toISOString(),
                end_date: endDate.toISOString(),
                target_buckets: 120,
              }),
            }
          );

          if (!response.ok) {
            console.warn(
              `[Statistics] Backend returned ${response.status}, falling back to demo data.`
            );
            throw new Error(`Status ${response.status}`);
          }
          data = await response.json();
        } catch (fetchErr) {
          console.warn(
            "[Statistics] Main fetch failed, using demo data",
            fetchErr
          );
          usedMock = true;
          data = MOCK_RESPONSE;
          setIsUsingDemoData(true);
          setStats(null);
        }

        if (data?.stats) {
          const rangeStart = data.range?.start
            ? new Date(data.range.start)
            : startDate;
          const rangeEnd = data.range?.end ? new Date(data.range.end) : endDate;
          const labeled = applyTimeSeriesLabels(
            data.stats.timeSeries || [],
            rangeStart,
            rangeEnd
          );
          setStats({ ...data.stats, timeSeries: labeled });
          setAllRows([]);
        } else if (usedMock && data) {
          // Fallback mock path still uses client-side computation
          setAllRows(MOCK_RESPONSE.rows || []);
          setIsUsingDemoData(true);
          setStats(computeStats(MOCK_RESPONSE.rows || []));
        } else {
          throw new Error("Unexpected stats payload");
        }
      } catch (err) {
        console.error("[Statistics] Unexpected error in fetchStats", err);
        setAllRows(MOCK_RESPONSE.rows || []);
        setIsUsingDemoData(true);
        setError(null);
        setStats(computeStats(MOCK_RESPONSE.rows || []));
      } finally {
        setRefreshing(false);
      }
    },
    [apiKey, timeWindow, customRange, applyTimeSeriesLabels, computeStats]
  );

  const fetchVramStats = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false;
    if (isUsingDemoData) {
      // In demo mode, show mock VRAM data
      // Re-calculate vramDayDate locally here
      const now = new Date(nowRef);
      const vramDayDate = new Date(
        Date.UTC(
          now.getUTCFullYear(),
          now.getUTCMonth(),
          now.getUTCDate() - vramDayOffset
        )
      );

      const mockProviders = buildMockVramProviders(vramDayDate);
      setVramError(null);
      processVramData(mockProviders, "day", vramDayDate);
      return;
    }

    if (!silent) setIsVramLoading(true);
    setVramError(null);

    // Calculate vramDayDate
    const now = new Date(nowRef);
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

      if (vramResponse.ok) {
        const vramData = await vramResponse.json();
        if (vramData?.error) {
          console.warn(
            "[Statistics] VRAM stats error, falling back to mock",
            vramData.error
          );
          const mockProviders = buildMockVramProviders(vramDayDate);
          setVramError(null);
          processVramData(mockProviders, "day", vramDayDate);
        } else {
          console.log("[Statistics] VRAM stats response", {
            day: vramDayStr,
            providers: vramData?.providers?.length ?? 0,
          });

          if (vramData.providers) {
            const signature = buildVramSignature(vramData.providers || []);
            if (signature === vramSignatureRef.current) {
              if (!silent) setIsVramLoading(false);
              return;
            }
            vramSignatureRef.current = signature;
            processVramData(vramData.providers || [], "day", vramDayDate);
          } else {
            const mockProviders = buildMockVramProviders(vramDayDate);
            setVramError(null);
            processVramData(mockProviders, "day", vramDayDate);
          }
        }
      } else {
        console.warn("[Statistics] VRAM stats fetch failed");
        // Fallback mock
        const mockProviders = buildMockVramProviders(vramDayDate);
        processVramData(mockProviders, "day", vramDayDate);
      }
    } catch (e) {
      console.error("[Statistics] Error fetching VRAM stats", e);
      const mockProviders = buildMockVramProviders(vramDayDate);
      setVramError(null);
      processVramData(mockProviders, "day", vramDayDate);
    } finally {
      if (!silent) setIsVramLoading(false);
    }
  }, [
    apiKey,
    vramDayOffset,
    nowRef,
    isUsingDemoData,
    buildMockVramProviders,
    processVramData,
    vramSignatureRef,
  ]);

  // Separate effect for VRAM fetching
  useEffect(() => {
    fetchVramStats();
  }, [fetchVramStats]);

  // Poll VRAM utilization every 5 seconds
  useEffect(() => {
    let isMounted = true;
    const tick = async () => {
      if (!isMounted) return;
      await fetchVramStats({ silent: true });
    };
    const intervalId = setInterval(tick, 5000);
    return () => {
      isMounted = false;
      clearInterval(intervalId);
    };
  }, [fetchVramStats]);

  // Poll for latest requests every 2 seconds
  useEffect(() => {
    let isMounted = true;
    const fetchLatest = async () => {
      try {
        const response = await fetch(`${API_BASE}/logosdb/latest_requests`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            logos_key: apiKey || "",
            Authorization: `Bearer ${apiKey}`,
          },
        });
        if (response.ok && isMounted) {
          const reqData = await response.json();
          if (reqData.requests) {
            const newRequests = reqData.requests as RequestItem[];
            const currentIds = latestRequestsRef.current.map(r => r.request_id).join(',');
            const newIds = newRequests.map(r => r.request_id).join(',');

            if (currentIds !== newIds) {
              LayoutAnimation.configureNext(LayoutAnimation.Presets.spring);
            }
            setLatestRequests(newRequests);
            // setLatestRequestsError(null); // Keep error state clean if success
          }
        } else if (!response.ok && isMounted) {
          // We might not want to show transient errors every 2s, but for initial load it's good.
          // Let's only set error if we have NO requests yet, or just log warn?
          // User asked for "refresh button should be just for... cumulative request volume chart... update the clouds pls".
          // User also asked: "Add also some information when the fetch was unsuccessful (only the first one )"
          if (latestRequests.length === 0) {
            setLatestRequestsError(`Status ${response.status}`);
          }
        }
      } catch (err) {
        console.warn("[Statistics] Failed to poll latest requests", err);
        if (isMounted && latestRequests.length === 0) {
          setLatestRequestsError("Connection failed");
        }
      }
    };

    // Initial fetch
    fetchLatest();

    const intervalId = setInterval(fetchLatest, 2000);
    return () => {
      isMounted = false;
      clearInterval(intervalId);
    };
  }, [apiKey]);

  // Initial + custom-range-driven fetch for main stats
  useEffect(() => {
    // Avoid double fire on mount; still refetch on any range change
    if (!initialFetchDone.current) {
      initialFetchDone.current = true;
      fetchStats();
      return;
    }
    fetchStats();
  }, [fetchStats, customRange]);

  // onRefresh for pull-to-refresh refreshes everything
  const onRefresh = useCallback(() => {
    fetchStats();
    fetchVramStats();
  }, [fetchStats, fetchVramStats]);

  // onRefreshCharts only refreshes the charts (shows skeletons during fetch)
  const onRefreshCharts = useCallback(async () => {
    setChartsRefreshing(true);
    await fetchStats();
    setChartsRefreshing(false);
  }, [fetchStats]);

  const handleClearCustomRange = useCallback(() => {
    setCustomRange(null);
    setShowRangeBadge(false);
    rangeBadgeAnim.setValue(0);
    fetchStats();
  }, [fetchStats, rangeBadgeAnim]);

  // Show/hide badge with same vibe as the approve button, but 200ms
  useEffect(() => {
    if (customRange) {
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

    // Check data volume. If too many points > 200, maybe sample?
    // For now map all.
    let accTotal = 0;
    let accCloud = 0;
    let accLocal = 0;

    const firstTs = stats.timeSeries[0]?.timestamp ?? 0;
    const lastTs =
      stats.timeSeries[stats.timeSeries.length - 1]?.timestamp ?? firstTs;
    const durationMs = Math.max(0, lastTs - firstTs);
    const isLongRange = durationMs > 3 * 24 * 3600 * 1000; // > 3 days

    const formatXAxisLabel = (ts: number) => {
      const date = new Date(ts);
      if (isLongRange) {
        // Example: "Jan 01"
        const month = date.toLocaleString("en-US", { month: "short" });
        const day = String(date.getDate()).padStart(2, "0");
        return `${month} ${day}`;
      }
      // Example: "1/12 11:00"
      const day = date.getDate();
      const monthNum = date.getMonth() + 1;
      const time = date.toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
      // Use space instead of newline for single line
      return `${day}/${monthNum} ${time}`;
    };

    const total: any[] = [];
    const cloud: any[] = [];
    const local: any[] = [];

    stats.timeSeries.forEach((e) => {
      accTotal += e.total;
      accCloud += e.cloud;
      accLocal += e.local;

      // Reformat label if present
      let label = "";
      if (e.label) label = formatXAxisLabel(e.timestamp);

      const labelComponent = label
        ? () => (
            <View style={{ width: 100, marginLeft: -50, marginTop: -30 }}>
              <Text
                style={{
                  color: "#64748B",
                  fontSize: 11,
                  textAlign: "center",
                  lineHeight: 14,
                }}
              >
                {label}
              </Text>
            </View>
          )
        : undefined;

      // ... (rest of code) ...

      total.push({
        value: accTotal,
        labelComponent: labelComponent,
        dataPointText: "",
        timestamp: e.timestamp,
      });
      cloud.push({
        value: accCloud,
        labelComponent: labelComponent,
        dataPointText: "",
        timestamp: e.timestamp,
      });
      local.push({
        value: accLocal,
        labelComponent: labelComponent,
        dataPointText: "",
        timestamp: e.timestamp,
      });
    });

    return { totalLineData: total, cloudLineData: cloud, localLineData: local };
  }, [stats]);

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
    const palette = [
      CHART_PALETTE.local,
      CHART_PALETTE.cloud,
      CHART_PALETTE.provider2,
      CHART_PALETTE.provider3,
      CHART_PALETTE.provider1,
    ];
    return (stats?.modelBreakdown ?? []).slice(0, 5).map((m, index) => ({
      value: m.requestCount,
      color: palette[index % palette.length],
      text: m.modelName,
    }));
  }, [stats]);

  return (
    <ScrollView
      className="w-full"
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
      }
      showsVerticalScrollIndicator={false}
    >
      <VStack className="w-full space-y-4">
        <Text
          size="2xl"
          className="text-center font-bold text-black dark:text-white"
        >
          Statistics
        </Text>

        {isUsingDemoData && (
          <Box className="mb-4 w-full rounded-lg border border-amber-500/20 bg-amber-500/10 p-3">
            <Text className="text-center font-medium text-amber-500">
              Running in Demo Mode (Backend Unavailable)
            </Text>
          </Box>
        )}

        {stats ? (
          <VStack space="lg">
            {/* Latest Requests + VRAM Utilization */}
            <View className="w-full flex-col gap-4 xl:flex-row xl:items-stretch xl:gap-8">
              <View className="w-full xl:flex-1">
                <RequestStack
                  requests={latestRequests}
                  error={latestRequestsError}
                />
              </View>
              <View className="hidden xl:flex w-px bg-outline-200 mx-4" />
              <View className="w-full xl:flex-1">
                <ChartCard
                  title="VRAM Utilization"
                  subtitle="Latest snapshot per Ollama provider"
                  className="h-full"
                >
                  {(width) => {
                    if (isVramLoading) {
                      return (
                        <Skeleton
                          variant="rounded"
                          className="rounded-lg"
                          style={{ height: 320 }}
                          startColor="bg-secondary-300"
                        />
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
                            onValueChange={(val) => setSelectedVramProvider(val || null)}
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

                        {(() => {
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
                              style={{ width: innerRadius * 2, height: innerRadius * 2 }}
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
                                  {d.text}: {d.value.toFixed(1)} GB
                                </Text>
                              </HStack>
                            ))}
                          </VStack>
                        </View>
                          );
                        })()}
                      </VStack>
                    );
                  }}
                </ChartCard>
              </View>
            </View>

            <View className="mt-8 h-[1px] w-full bg-outline-200" />

            {/* Controls Container */}
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                marginTop: 24,
                marginBottom: 24,
                paddingHorizontal: 12,
                gap: 12, // Gap between range badge and refresh button
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

              <Button
                variant="outline"
                action="secondary"
                size="sm"
                onPress={onRefreshCharts}
                className="rounded-full border-outline-200"
                disabled={refreshing || chartsRefreshing}
              >
                <HStack space="sm" className="items-center">
                  <ButtonIcon as={RotateCw} size="sm" />
                  <Text className="font-medium text-typography-700">
                    Refresh Charts
                  </Text>
                </HStack>
              </Button>
            </View>

            {/* Main Volume Chart Card */}
            {chartsRefreshing || !stats?.timeSeries?.length ? (
              <Skeleton
                variant="rounded"
                className="w-full rounded-lg"
                style={{ height: 420 }}
                startColor="bg-secondary-300"
              />
            ) : (
              <ChartCard
                title="Cumulative Request Volume (Total vs Cloud vs Local)"
                subtitle="Drag horizontally to select a custom time range"
              >
                {(width) => (
                  <View>
                    {/* Legend */}
                    <View
                      style={{
                        flexDirection: "row",
                        justifyContent: "flex-start",
                        marginBottom: 10,
                        paddingHorizontal: 10,
                      }}
                    >
                      <View
                        style={{
                          flexDirection: "row",
                          alignItems: "center",
                          marginRight: 16,
                        }}
                      >
                        <View
                          style={{
                            width: 12,
                            height: 12,
                            borderRadius: 2,
                            backgroundColor: CHART_PALETTE.total,
                            marginRight: 6,
                          }}
                        />
                        <Text
                          style={{
                            fontSize: 12,
                            color: CHART_PALETTE.textLight,
                          }}
                        >
                          Total
                        </Text>
                      </View>
                      <View
                        style={{
                          flexDirection: "row",
                          alignItems: "center",
                          marginRight: 16,
                        }}
                      >
                        <View
                          style={{
                            width: 12,
                            height: 12,
                            borderRadius: 2,
                            backgroundColor: CHART_PALETTE.cloud,
                            marginRight: 6,
                          }}
                        />
                        <Text
                          style={{
                            fontSize: 12,
                            color: CHART_PALETTE.textLight,
                          }}
                        >
                          Cloud
                        </Text>
                      </View>
                      <View
                        style={{
                          flexDirection: "row",
                          alignItems: "center",
                          marginRight: 16,
                        }}
                      >
                        <View
                          style={{
                            width: 12,
                            height: 12,
                            borderRadius: 2,
                            backgroundColor: CHART_PALETTE.local,
                            marginRight: 6,
                          }}
                        />
                        <Text
                          style={{
                            fontSize: 12,
                            color: CHART_PALETTE.textLight,
                          }}
                        >
                          Local
                        </Text>
                      </View>
                    </View>

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
                  </View>
                )}
              </ChartCard>
            )}

            <HStack space="md" className="w-full">
              <View style={{ flex: 1 }}>
                {chartsRefreshing || !providerPieData.length ? (
                  <Skeleton
                    variant="rounded"
                    className="rounded-lg"
                    style={{ height: 600 }}
                    startColor="bg-secondary-300"
                  />
                ) : (
                  <ChartCard title="Request Type" className="flex-1">
                    {(width) => {
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
                              style={{ width: innerRadius * 2, height: innerRadius * 2 }}
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
                )}
              </View>
              <View style={{ flex: 1 }}>
              {chartsRefreshing || !modelPieData.length ? (
                  <Skeleton
                    variant="rounded"
                    className="rounded-lg"
                    style={{ height: 600 }}
                    startColor="bg-secondary-300"
                  />
                ) : (
                  <ChartCard title="Model Share" className="flex-1">
                      {(width) => {
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
                                style={{ width: innerRadius * 2, height: innerRadius * 2 }}
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
                  )}
                </View>
              </HStack>

            <View className="my-12 h-[1px] w-full bg-outline-200" />

            <ChartCard title="VRAM Remaining" subtitle="Per Ollama-Provider">
              {(width) => (
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
                  nowRef={nowRef}
                />
              )}
            </ChartCard>
          </VStack>
        ) : (
          <Text className="text-center text-red-500">
            {error || "Unable to load statistics."}
          </Text>
        )}
      </VStack>
    </ScrollView>
  );
}
