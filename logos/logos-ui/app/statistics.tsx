import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Easing, PanResponder, Platform, RefreshControl, ScrollView, View } from 'react-native';
import { LineChart, PieChart } from 'react-native-gifted-charts';

import { useAuth } from '@/components/auth-shell';
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonIcon } from "@/components/ui/button";

import { CheckIcon, CloseIcon } from '@/components/ui/icon';
import { RotateCw } from 'lucide-react-native';
import { ActivityIndicator, Appearance } from 'react-native';

type RequestEventRow = {
  request_id: string;
  model_id: number | null;
  provider_id: number | null;
  initial_priority: string | null;
  priority_when_scheduled: string | null;
  queue_depth_at_enqueue: number | null;
  queue_depth_at_schedule: number | null;
  timeout_s: number | null;
  enqueue_ts: string | null;
  scheduled_ts: string | null;
  request_complete_ts: string | null;
  available_vram_mb: number | null;
  azure_rate_remaining_requests: number | null;
  azure_rate_remaining_tokens: number | null;
  cold_start: boolean | null;
  result_status: string | null;
  error_message: string | null;
};

type RequestEventResponse = {
  stats?: RequestEventStats;
  bucketSeconds?: number;
  range?: { start: string; end: string };
  rows?: RequestEventRow[];
};

type RequestEventStats = {
  lastEventTs: string | null;
  totals: {
    requests: number;
    cloudRequests: number;
    localRequests: number;
    coldStarts: number;
    warmStarts: number;
    avgQueueSeconds: number | null;
    avgRunSeconds: number | null;
  };
  statusCounts: Record<string, number>;
  modelBreakdown: Array<{
    modelId: number;
    modelName: string;
    providerName: string;
    requestCount: number;
    avgQueueSeconds: number | null;
    avgRunSeconds: number | null;
    coldStarts: number;
    warmStarts: number;
    errorCount: number;
  }>;
  timeSeries: Array<{
    timestamp: number; // Unix ts
    label: string;
    cloud: number;
    local: number;
    total: number;
    avgRunSeconds: number | null;
    avgVram: number | null;
  }>;
  queueDepth: {
    avgEnqueueDepth: number | null;
    avgScheduleDepth: number | null;
    p95EnqueueDepth: number | null;
    p95ScheduleDepth: number | null;
  } | null;
  runtimeByColdStart: Array<{
    type: 'cold' | 'warm';
    avgRunSeconds: number | null;
    count: number;
  }>;
};

const BASE_MOCK_ROWS: RequestEventRow[] = [
  {
    request_id: "seed-1",
    model_id: 10,
    provider_id: 2,
    initial_priority: "normal",
    priority_when_scheduled: "normal",
    queue_depth_at_enqueue: 0,
    queue_depth_at_schedule: 0,
    timeout_s: null,
    enqueue_ts: "2025-12-28T20:31:42.957755+00:00",
    scheduled_ts: "2025-12-28T20:31:42.982784+00:00",
    request_complete_ts: "2025-12-28T20:31:50.800739+00:00",
    available_vram_mb: null,
    azure_rate_remaining_requests: 999,
    azure_rate_remaining_tokens: 999988,
    cold_start: false,
    result_status: "success",
    error_message: null
  },
  {
    request_id: "seed-2",
    model_id: 15,
    provider_id: 6,
    initial_priority: "normal",
    priority_when_scheduled: "normal",
    queue_depth_at_enqueue: 0,
    queue_depth_at_schedule: 0,
    timeout_s: null,
    enqueue_ts: "2025-12-28T20:34:23.502786+00:00",
    scheduled_ts: "2025-12-28T20:34:23.650881+00:00",
    request_complete_ts: "2025-12-28T20:34:46.176515+00:00",
    available_vram_mb: 12500,
    azure_rate_remaining_requests: null,
    azure_rate_remaining_tokens: null,
    cold_start: true,
    result_status: "success",
    error_message: null
  },
  {
    request_id: "seed-3",
    model_id: 14,
    provider_id: 6,
    initial_priority: "normal",
    priority_when_scheduled: "normal",
    queue_depth_at_enqueue: 0,
    queue_depth_at_schedule: 0,
    timeout_s: null,
    enqueue_ts: "2025-12-28T20:32:11.733902+00:00",
    scheduled_ts: "2025-12-28T20:32:11.875745+00:00",
    request_complete_ts: "2025-12-28T20:32:42.000098+00:00",
    available_vram_mb: 12500,
    azure_rate_remaining_requests: null,
    azure_rate_remaining_tokens: null,
    cold_start: false,
    result_status: "error",
    error_message: ""
  },
  {
    request_id: "seed-4",
    model_id: 33,
    provider_id: 6,
    initial_priority: "normal",
    priority_when_scheduled: "normal",
    queue_depth_at_enqueue: 0,
    queue_depth_at_schedule: 0,
    timeout_s: null,
    enqueue_ts: "2025-12-28T20:24:15.047690+00:00",
    scheduled_ts: "2025-12-28T20:24:15.191829+00:00",
    request_complete_ts: "2025-12-28T20:24:44.455808+00:00",
    available_vram_mb: 12500,
    azure_rate_remaining_requests: null,
    azure_rate_remaining_tokens: null,
    cold_start: false,
    result_status: "success",
    error_message: null
  },
  {
    request_id: "seed-5",
    model_id: 23,
    provider_id: 2,
    initial_priority: "normal",
    priority_when_scheduled: "normal",
    queue_depth_at_enqueue: 0,
    queue_depth_at_schedule: 0,
    timeout_s: null,
    enqueue_ts: "2025-12-28T20:25:29.251006+00:00",
    scheduled_ts: "2025-12-28T20:25:29.281297+00:00",
    request_complete_ts: "2025-12-28T20:25:34.007126+00:00",
    available_vram_mb: null,
    azure_rate_remaining_requests: 999,
    azure_rate_remaining_tokens: 999996,
    cold_start: false,
    result_status: "success",
    error_message: null
  }
];

const buildMockRows = (count: number, daysBack: number = 30): RequestEventRow[] => {
  const rows: RequestEventRow[] = [];
  const now = Date.now();
  const start = now - daysBack * 24 * 60 * 60 * 1000;

  const uuidish = (i: number) => {
    const hex = (n: number, len = 4) => n.toString(16).padStart(len, "0");
    return `${hex(i, 8)}-${hex(i * 3)}-${hex(i * 5)}-${hex(i * 7)}-${hex(i * 11)}${hex(i * 13, 8)}`;
  };

  for (let i = 0; i < count; i++) {
    const base = BASE_MOCK_ROWS[i % BASE_MOCK_ROWS.length];
    // Random distribution over the time range, favoring more recent times slightly
    const randomOffset = Math.random() * (daysBack * 24 * 60 * 60 * 1000);
    const time = start + randomOffset;
    
    const enqueue = new Date(time);
    const scheduled = new Date(enqueue.getTime() + 50 + Math.random() * 500); // 50-550ms queue
    const complete = new Date(scheduled.getTime() + 1000 + Math.random() * 20000); // 1-21s run

    const isCold = Math.random() < 0.2 ? true : base.cold_start; // 20% cold chance
    const failChance = Math.random();
    const status = failChance < 0.05 ? "error" : (failChance < 0.08 ? "failed" : "success");
    
    // VRAM simulation: fluctuaties over time + random noise
    // Sine wave pattern for "load"
    const hour = enqueue.getHours();
    const loadFactor = (Math.sin(hour / 3) + 1) / 2; // 0 to 1
    const availableVram = 8000 + loadFactor * 16000 + Math.random() * 2000;

    const enqueueDepth = Math.floor(Math.random() * 5) + (hour > 12 ? 2 : 0);
    const scheduleDepth = Math.floor(Math.random() * 5);

    rows.push({
      request_id: uuidish(i + 1),
      model_id: base.model_id,
      provider_id: Math.random() > 0.6 ? 2 : 6, // 40% cloud (2), 60% local (6)
      initial_priority: base.initial_priority,
      priority_when_scheduled: base.priority_when_scheduled,
      queue_depth_at_enqueue: enqueueDepth,
      queue_depth_at_schedule: scheduleDepth,
      timeout_s: base.timeout_s,
      enqueue_ts: enqueue.toISOString(),
      scheduled_ts: scheduled.toISOString(),
      request_complete_ts: complete.toISOString(),
      available_vram_mb: availableVram,
      azure_rate_remaining_requests: base.provider_id === 2 ? 900 - (i % 10) * 5 : null,
      azure_rate_remaining_tokens: base.provider_id === 2 ? 900000 - (i % 20) * 1000 : null,
      cold_start: isCold,
      result_status: status,
      error_message: status !== "success" ? (status === "failed" ? "provider timeout" : "error") : null,
    });
  }
  // Sort by enqueue time
  return rows.sort((a, b) => new Date(a.enqueue_ts!).getTime() - new Date(b.enqueue_ts!).getTime());
};

const MAX_MOCK_ROWS = 2000;
const MOCK_RESPONSE: RequestEventResponse = {
  rows: buildMockRows(MAX_MOCK_ROWS, 30) // 30 days
};

const API_BASE =
  Platform.OS === 'web'
    ? ''
    : process.env.EXPO_PUBLIC_API_BASE || 'http://localhost:8080';

const formatRangeLabel = (range: { start: Date; end: Date }) => {
  const format = (d: Date) =>
    `${(d.getMonth() + 1).toString().padStart(2, '0')}/${d
      .getDate()
      .toString()
      .padStart(2, '0')}`;
  return `${format(range.start)} → ${format(range.end)}`;
};

const applyTimeSeriesLabels = (
  series: RequestEventStats['timeSeries'],
  rangeStart: Date,
  rangeEnd: Date
): RequestEventStats['timeSeries'] => {
  if (!series.length) return [];

  const durationMs = Math.max(rangeEnd.getTime() - rangeStart.getTime(), 0);
  const labelStep = Math.max(1, Math.ceil(series.length / 10));
  let lastLabel = '';

  return series.map((pt, idx) => {
    const next = { ...pt };
    if (idx % labelStep === 0) {
      const date = new Date(pt.timestamp);
      let newLabel = '';
      if (durationMs < 24 * 3600 * 1000) {
        newLabel = date.toLocaleTimeString("en-GB", { hour: '2-digit', minute: '2-digit', hour12: false });
      } else if (durationMs < 7 * 24 * 3600 * 1000) {
        newLabel = date.toLocaleDateString("en-US", { month: "short", day: "numeric" }) + ` ${date.getHours()}h`;
      } else {
        newLabel = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
      }
      if (newLabel !== lastLabel) {
        next.label = newLabel;
        lastLabel = newLabel;
      }
    }
    return next;
  });
};

const calculateDateRange = (
    period: string,
    customRange?: { start: Date; end: Date } | null
): { startDate: Date; endDate: Date } => {
    const endDate = new Date();
    let startDate = new Date();

    if (period === "custom" && customRange) {
      return { startDate: customRange.start, endDate: customRange.end };
    }

    switch (period) {
      case "24h":
        startDate.setHours(startDate.getHours() - 24);
        break;
      case "7d":
        startDate.setDate(startDate.getDate() - 7);
        break;
      case "30d":
        startDate.setDate(startDate.getDate() - 30);
        break;
    }

    return { startDate, endDate };
};

export default function Statistics() {
  const { apiKey } = useAuth();
  
  // State
  const timeWindow: '30d' = '30d';
  const [customRange, setCustomRange] = useState<{ start: Date; end: Date } | null>(null);
  const [showRangeBadge, setShowRangeBadge] = useState(false);
  const rangeBadgeAnim = useRef(new Animated.Value(0)).current;
  
  // Data
  const [stats, setStats] = useState<RequestEventStats | null>(null);
  const [allRows, setAllRows] = useState<RequestEventRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [vramError, setVramError] = useState<string | null>(null);
  const [isUsingDemoData, setIsUsingDemoData] = useState(false);
  const [nowRef] = useState<number>(Date.now()); // Stable hydration
  const [vramDayOffset, setVramDayOffset] = useState(0); // 0 = today, 1 = yesterday, etc.
  const [vramDataByProvider, setVramDataByProvider] = useState<{
    [url: string]: Array<{ value: number; label: string; timestamp: string }>;
  }>({});
  const [vramBaseline, setVramBaseline] = useState<any[]>([]);
  const [vramBucketSizeSec, setVramBucketSizeSec] = useState(10);
  const [vramTotalBuckets, setVramTotalBuckets] = useState(8640);
  const initialFetchDone = useRef(false);

  // Compute filtered rows
  const filteredRows = useMemo(() => {
    if (!allRows.length) return [];
    
    let rows = [...allRows];

    if (customRange) {
      rows = rows.filter(r => {
        if (!r.enqueue_ts) return false;
        const t = new Date(r.enqueue_ts);
        return t >= customRange.start && t <= customRange.end;
      });
    } else {
      // Default to 30-day window
      const now = new Date(nowRef);
      const cutoff = new Date(nowRef);
      if (timeWindow === '30d') cutoff.setDate(now.getDate() - 30);
      else if (timeWindow === '7d') cutoff.setDate(now.getDate() - 7);
      else if (timeWindow === '24h') cutoff.setHours(now.getHours() - 24);
      rows = rows.filter(r => r.enqueue_ts && new Date(r.enqueue_ts) >= cutoff);
    }
    return rows;
  }, [allRows, timeWindow, customRange, nowRef]);

  // Recalculate stats whenever filteredRows changes
  const computeStats = useCallback((rows: RequestEventRow[]): RequestEventStats => {
    const toDate = (v: string | null) => (v ? new Date(v) : null);
    const avg = (arr: number[]) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);

    const allTimes: Date[] = [];
    rows.forEach(r => {
      ['request_complete_ts', 'scheduled_ts', 'enqueue_ts'].forEach((k) => {
        const val = (r as any)[k] as string | null;
        if (val) {
          const d = new Date(val);
          if (!isNaN(d.getTime())) allTimes.push(d);
        }
      });
    });
    const lastEvent = allTimes.length ? new Date(Math.max(...allTimes.map(d => d.getTime()))) : null;

    const statusCounts: Record<string, number> = {};
    rows.forEach(r => {
      const key = (r.result_status || 'unknown').toLowerCase();
      statusCounts[key] = (statusCounts[key] || 0) + 1;
    });

    const totals = {
      requests: rows.length,
      cloudRequests: rows.filter(r => r.provider_id === 2).length,
      localRequests: rows.filter(r => r.provider_id !== 2).length,
      coldStarts: rows.filter(r => r.cold_start === true).length,
      warmStarts: rows.filter(r => r.cold_start === false || r.cold_start === null).length,
      avgQueueSeconds: null as number | null,
      avgRunSeconds: null as number | null,
    };

    const queueDurations: number[] = [];
    const runDurations: number[] = [];
    rows.forEach(r => {
      const enq = toDate(r.enqueue_ts);
      const sched = toDate(r.scheduled_ts);
      const done = toDate(r.request_complete_ts);
      if (enq && sched) queueDurations.push((sched.getTime() - enq.getTime()) / 1000);
      if (sched && done) runDurations.push((done.getTime() - sched.getTime()) / 1000);
    });
    totals.avgQueueSeconds = avg(queueDurations);
    totals.avgRunSeconds = avg(runDurations);

    const modelMap: Record<number, RequestEventRow[]> = {};
    rows.forEach(r => {
      const id = r.model_id ?? -1;
      if (!modelMap[id]) modelMap[id] = [];
      modelMap[id].push(r);
    });
    const modelBreakdown = Object.entries(modelMap).map(([id, list]) => {
      const rqDur: number[] = [];
      const runDur2: number[] = [];
      list.forEach(r => {
        const enq = toDate(r.enqueue_ts);
        const sched = toDate(r.scheduled_ts);
        const done = toDate(r.request_complete_ts);
        if (enq && sched) rqDur.push((sched.getTime() - enq.getTime()) / 1000);
        if (sched && done) runDur2.push((done.getTime() - sched.getTime()) / 1000);
      });
      const errors = list.filter(r => (r.result_status && r.result_status !== 'success') || (r.error_message && r.error_message.length)).length;
      return {
        modelId: Number(id),
        modelName: `Model ${id}`,
        providerName: list[0]?.provider_id ? `Provider ${list[0].provider_id}` : 'Provider',
        requestCount: list.length,
        avgQueueSeconds: avg(rqDur),
        avgRunSeconds: avg(runDur2),
        coldStarts: list.filter(r => r.cold_start === true).length,
        warmStarts: list.filter(r => r.cold_start === false || r.cold_start === null).length,
        errorCount: errors,
      };
    }).sort((a, b) => b.requestCount - a.requestCount);

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
        if (timeWindow === '30d') startTs = now - 30 * 24 * 3600 * 1000;
        else if (timeWindow === '7d') startTs = now - 7 * 24 * 3600 * 1000;
        else if (timeWindow === '24h') startTs = now - 24 * 3600 * 1000;
    }
    const durationMs = endTs - startTs;
    const targetPoints = 120; // Target resolution
    let rawBucketMs = durationMs / targetPoints;

    // Snap to nice intervals
    const niceIntervals = [
      60 * 1000,          // 1m
      5 * 60 * 1000,      // 5m
      15 * 60 * 1000,     // 15m
      60 * 60 * 1000,     // 1h
      4 * 60 * 60 * 1000, // 4h
      12 * 60 * 60 * 1000,// 12h
      24 * 60 * 60 * 1000 // 1d
    ];
    // Find closest nice interval, default to raw if nothing close (or just use raw for max precision?)
    // Let's use raw for max precision so it fits exactly, or just snap to nearest larger nice one?
    // User wants "visible spikes". Strict 120 points is good.
    // But buckets align better if they are round numbers.
    let bucketMs = niceIntervals.reduce((prev, curr) => 
      Math.abs(curr - rawBucketMs) < Math.abs(prev - rawBucketMs) ? curr : prev
    );
    // Ensure we don't go too small or too large if outside bounds
    if (rawBucketMs < 60 * 1000) bucketMs = 60 * 1000; 

    const bucketMap: Record<number, { cloud: number; local: number; run: number[]; vram: number[] }> = {};
    
    rows.forEach(r => {
      const ts = r.scheduled_ts ? new Date(r.scheduled_ts).getTime() : (r.enqueue_ts ? new Date(r.enqueue_ts).getTime() : 0);
      if (!ts) return;
      
      const bucket = Math.floor(ts / bucketMs) * bucketMs;
      if (!bucketMap[bucket]) bucketMap[bucket] = { cloud: 0, local: 0, run: [], vram: [] };
      
      const isCloud = r.provider_id === 2;
      if (isCloud) bucketMap[bucket].cloud++;
      else bucketMap[bucket].local++;
      
      const done = toDate(r.request_complete_ts);
      const start = toDate(r.scheduled_ts);
      if (done && start) bucketMap[bucket].run.push((done.getTime() - start.getTime()) / 1000);
      if (r.available_vram_mb) bucketMap[bucket].vram.push(r.available_vram_mb);
    });

    const timeSeries = Object.entries(bucketMap)
      .map(([tsStr, data]) => {
        const ts = Number(tsStr);
        // Labeling logic happens later to avoid clutter
        return {
            timestamp: ts,
            label: '', // Placeholder, populated below
            cloud: data.cloud,
            local: data.local,
            total: data.cloud + data.local,
            avgRunSeconds: avg(data.run),
            avgVram: avg(data.vram)
        };
      })
      .sort((a, b) => a.timestamp - b.timestamp);

    // Post-process labels: ~10 labels max
    const labelStep = Math.ceil(timeSeries.length / 10);
    let lastLabel = '';

    timeSeries.forEach((pt, idx) => {
        if (idx % labelStep === 0) {
            const date = new Date(pt.timestamp);
            let newLabel = '';
            // Smart formatting
            if (durationMs < 24 * 3600 * 1000) {
                // < 24h: Show time
                newLabel = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            } else if (durationMs < 7 * 24 * 3600 * 1000) {
                // < 7d: Show Day + Time or Date + Time
                // Showing MM/DD HH:mm for compactness
                newLabel = `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}h`;
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

    const enqueueDepths = rows.map(r => r.queue_depth_at_enqueue).filter((v): v is number => typeof v === 'number');
    const scheduleDepths = rows.map(r => r.queue_depth_at_schedule).filter((v): v is number => typeof v === 'number');
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

    const runtimeByColdStart = (['cold', 'warm'] as const).map(type => {
      const isCold = type === 'cold';
      const subset = rows.filter(r => (r.cold_start ?? false) === isCold);
      const runDurCold: number[] = [];
      subset.forEach(r => {
        const sched = toDate(r.scheduled_ts);
        const done = toDate(r.request_complete_ts);
        if (sched && done) runDurCold.push((done.getTime() - sched.getTime()) / 1000);
      });
      return {
        type: isCold ? 'cold' : 'warm',
        avgRunSeconds: avg(runDurCold),
        count: subset.length,
      } as { type: 'cold' | 'warm'; avgRunSeconds: number | null; count: number };
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
  }, [timeWindow, customRange, nowRef]);

  // Recompute stats locally only in demo/fallback mode
  useEffect(() => {
    if (!isUsingDemoData) return;
    setStats(computeStats(filteredRows));
  }, [isUsingDemoData, filteredRows, computeStats]);

  // Helper functions for VRAM data


  const formatTimestampLabel = useCallback((timestamp: string, period: string): string => {
    const date = new Date(timestamp);

    switch (period) {
      case "day":
        return date.toLocaleTimeString("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        });
      case "24h":
        return date.toLocaleTimeString("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        });
      case "7d":
      case "30d":
        return date.toLocaleDateString("en-US", {
          month: "short",
          day: "numeric"
        });
      default:
        return date.toLocaleString();
    }
  }, []);

  const resolveVramBucketSize = useCallback(() => {
    // Keep demo-mode lighter on web to avoid massive renders/refresh traversals
    if (Platform.OS === 'web' && isUsingDemoData) return 60; // 1m buckets in demo on web
    return 10; // 10s buckets otherwise
  }, [isUsingDemoData]);

  const processVramData = useCallback((providers: Array<{url: string; data: Array<any>}>, period: string, dayAnchor?: Date) => {
    const bucketSec = resolveVramBucketSize();
    const TOTAL_POINTS = Math.floor((24 * 3600) / bucketSec);
    
    // Determine start of the day (UTC)
    const dayStart = dayAnchor
      ? new Date(Date.UTC(dayAnchor.getUTCFullYear(), dayAnchor.getUTCMonth(), dayAnchor.getUTCDate()))
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
        const label = isHour ? date.toLocaleTimeString("en-GB", { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) : '';
        timeline.push({ timestamp: ts, label });
    }
    
    const getBucketIndex = (ts: number) => {
        const diff = ts - dayStartMs;
        if (diff < 0) return -1;
        const idx = Math.floor(diff / (bucketSec * 1000));
        return idx < TOTAL_POINTS ? idx : -1;
    };

    providers.forEach(p => {
        const buckets: Array<{ sum: number; count: number; raw: any } | null> = new Array(TOTAL_POINTS).fill(null);
        
        p.data.forEach(sample => {
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
                    _empty: true
                 };
            }
            
            // User wants "Remaining Memory" logic
            const raw = b.raw;
            const remainingMb = raw.remaining_vram_mb || 0;
            const remainingGb = Number((remainingMb / 1024).toFixed(2));
            const usedGb = Number(((raw.used_vram_mb || raw.vram_mb || 0) / 1024).toFixed(2));
            const loadedModelNames = (raw.loaded_models || []).map((m: any) => m.name);
            
            return {
                value: remainingGb, // Chart Remaining VRAM
                label: t.label, // Time label for hourly markers
                timestamp: t.timestamp,
                used_vram_gb: usedGb,
                remaining_vram_gb: remainingGb,
                models_loaded: raw.models_loaded ?? 0,
                loaded_model_names: loadedModelNames,
                // Ensure we have properties needed for render
                hideDataPoint: false, // Show data points
                dataPointRadius: 2,
                _empty: false
            };
        });
        processed[p.url] = lineData;
    });

    // Provide a baseline for the x-axis labels and total width.
    const baseline = timeline.map(t => ({ value: 0, label: t.label, _isBaseline: true }));
    
    setVramBucketSizeSec(bucketSec);
    setVramTotalBuckets(TOTAL_POINTS);
    setVramBaseline(baseline);
    setVramDataByProvider(processed);
  }, [resolveVramBucketSize]);

  // Mock VRAM data for troubleshooting when API fails
  const buildMockVramProviders = useCallback((day: Date) => {
    const base = new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate()));
    const points = 100;
    const spanMs = 24 * 3600 * 1000;
    const samples = Array.from({ length: points }).map((_, i) => {
      const ts = new Date(base.getTime() + (spanMs * i) / (points - 1)).toISOString();
      // oscillate between 6 GB and 24 GB free with slight noise
      const freeMb = 6000 + Math.abs(Math.sin(i / 8)) * 18000 + Math.random() * 800;
      const usedMb = Math.max(0, 32000 - freeMb);
      return {
        timestamp: ts,
        remaining_vram_mb: Math.round(freeMb),
        vram_mb: Math.round(usedMb),
        models_loaded: Math.floor(Math.random() * 4),
        loaded_models: [],
      };
    });
    return [{
      url: 'mock.provider',
      data: samples,
    }];
  }, []);

  // Central Palette
  const CHART_PALETTE = {
    total: '#1E3A8A', // Dark Blue for cumulative total
    cloud: '#3BE9DE', // Cyan
    local: '#F29C6E', // Orange for local
    provider1: '#F59E0B', // Amber
    provider2: '#9D4EDD', // Purple
    provider3: '#06FFA5', // Green
    textLight: '#64748B', // Slate-500 (readable on light)
    textDark: '#94A3B8',  // Slate-400 (readable on dark)
  };

  const VRAM_HOUR_SPACING_PX = 91; // ~30% more horizontal breathing room

  const PROVIDER_COLORS = [
    CHART_PALETTE.provider1,
    CHART_PALETTE.cloud,
    CHART_PALETTE.local,
    CHART_PALETTE.provider2,
    CHART_PALETTE.provider3,
  ];

  const getProviderColor = (index: number): string => {
    return PROVIDER_COLORS[index % PROVIDER_COLORS.length];
  };

    const [isVramLoading, setIsVramLoading] = useState(false);




  const fetchStats = useCallback(async () => {
    // Note: apiKey check skipped to allow demo mode or immediate mock fallback
    setRefreshing(true);
    setLoading(true);
    setError(null);
    setIsUsingDemoData(false);

    const rangePeriod = customRange ? 'custom' : timeWindow;
    const { startDate, endDate } = calculateDateRange(rangePeriod, customRange);
    
    // VRAM day calculation moved to fetchVramStats specifically, 
    // but we can keep 'now' ref if needed for other things.

    try {
      let data: RequestEventResponse | null = null;
      let usedMock = false;

      // Fetch aggregated request events
      try {
        const response = await fetch(`${API_BASE}/logosdb/request_event_stats`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'logos_key': apiKey || '',
            'Authorization': `Bearer ${apiKey}`,
          },
          body: JSON.stringify({
            logos_key: apiKey,
            start_date: startDate.toISOString(),
            end_date: endDate.toISOString(),
            target_buckets: 120
          }),
        });
        if (!response.ok) {
          console.warn(`[Statistics] Backend returned ${response.status}, falling back to demo data.`);
          throw new Error(`Status ${response.status}`);
        }
        data = await response.json();
      } catch (fetchErr) {
        console.warn('[Statistics] Main fetch failed, using demo data', fetchErr);
        usedMock = true;
        data = MOCK_RESPONSE;
        setIsUsingDemoData(true);
        setStats(null);
      }

        if (data?.stats) {
          const rangeStart = data.range?.start ? new Date(data.range.start) : startDate;
          const rangeEnd = data.range?.end ? new Date(data.range.end) : endDate;
          const labeled = applyTimeSeriesLabels(data.stats.timeSeries || [], rangeStart, rangeEnd);
          setStats({ ...data.stats, timeSeries: labeled });
          setAllRows([]);
        } else if (usedMock && data) {
          // Fallback mock path still uses client-side computation
          setAllRows(MOCK_RESPONSE.rows || []);
          setIsUsingDemoData(true);
          setStats(computeStats(MOCK_RESPONSE.rows || []));
        } else {
          throw new Error('Unexpected stats payload');
        }

    } catch (err) {
      console.error('[Statistics] Unexpected error in fetchStats', err);
      setAllRows(MOCK_RESPONSE.rows || []);
      setIsUsingDemoData(true);
      setError(null);
      setStats(computeStats(MOCK_RESPONSE.rows || []));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiKey, timeWindow, customRange, applyTimeSeriesLabels, computeStats]);

  const fetchVramStats = useCallback(async () => {
     if (isUsingDemoData) {
         // In demo mode, show mock VRAM data
         // Re-calculate vramDayDate locally here
         const now = new Date(nowRef);
         const vramDayDate = new Date(Date.UTC(
            now.getUTCFullYear(),
            now.getUTCMonth(),
            now.getUTCDate() - vramDayOffset
         ));
         
         const mockProviders = buildMockVramProviders(vramDayDate);
         setVramError(null);
         processVramData(mockProviders, 'day', vramDayDate);
         return;
     }

     setIsVramLoading(true);
     setVramError(null);
     
     // Calculate vramDayDate
     const now = new Date(nowRef);
     const vramDayDate = new Date(Date.UTC(
        now.getUTCFullYear(),
        now.getUTCMonth(),
        now.getUTCDate() - vramDayOffset
     ));
     const vramDayStr = vramDayDate.toISOString().slice(0, 10);
     
     try {
        const vramResponse = await fetch(`${API_BASE}/logosdb/get_ollama_vram_stats`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'logos_key': apiKey || '',
                'Authorization': `Bearer ${apiKey}`,
              },
              body: JSON.stringify({
                day: vramDayStr,
              }),
            });

            if (vramResponse.ok) {
              const vramData = await vramResponse.json();
              if (vramData?.error) {
                console.warn('[Statistics] VRAM stats error, falling back to mock', vramData.error);
                const mockProviders = buildMockVramProviders(vramDayDate);
                setVramError(null);
                processVramData(mockProviders, 'day', vramDayDate);
              } else {
                  console.log('[Statistics] VRAM stats response', {
                    day: vramDayStr,
                    providers: vramData?.providers?.length ?? 0
                  });
                  
                  if (vramData.providers) {
                     processVramData(vramData.providers || [], 'day', vramDayDate);
                  } else {
                     const mockProviders = buildMockVramProviders(vramDayDate);
                     setVramError(null);
                     processVramData(mockProviders, 'day', vramDayDate);
                  }
              }
            } else {
               console.warn('[Statistics] VRAM stats fetch failed');
               // Fallback mock
               const mockProviders = buildMockVramProviders(vramDayDate);
               processVramData(mockProviders, 'day', vramDayDate);
            }
     } catch (e) {
        console.error('[Statistics] Error fetching VRAM stats', e);
        const mockProviders = buildMockVramProviders(vramDayDate);
        setVramError(null);
        processVramData(mockProviders, 'day', vramDayDate);
     } finally {
        setIsVramLoading(false);
     }
  }, [apiKey, vramDayOffset, nowRef, isUsingDemoData, buildMockVramProviders, processVramData]);

  // Separate effect for VRAM fetching
  useEffect(() => {
     fetchVramStats();
  }, [fetchVramStats]);

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

  const onRefresh = useCallback(() => {
      fetchStats();
      fetchVramStats();
  }, [fetchStats, fetchVramStats]);

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

  const modelBarData = useMemo(() => {
    return (stats?.modelBreakdown ?? [])
    .slice(0, 6)
    .map((m, index) => {
      const isCyan = index % 2 !== 0;
      return {
        value: m.requestCount || 0,
        label: m.modelName.length > 10 ? `${m.modelName.slice(0, 9)}…` : m.modelName,
        frontColor: isCyan ? '#3BE9DE' : '#006DFF',
        gradientColor: isCyan ? '#93FCF8' : '#009FFF',
        showGradient: true,
        topLabelComponent: () => (
          <Text className="text-xs text-white mb-1 font-medium">{m.requestCount}</Text>
        ),
      };
    });
  }, [stats]);

  const statusPieData = useMemo(() => {
    if (!stats) return [];
    const colors: Record<string, string> = {
      success: '#22c55e',
      failed: '#ef4444',
      error: '#ef4444',
      unknown: '#94a3b8',
    };
    return Object.entries(stats.statusCounts || {})
      .filter(([, count]) => count > 0)
      .map(([status, count]) => ({
        value: count,
        color: colors[status] || '#6366f1',
        text: `${status} (${count})`,
        onPress: () => console.log('pressed', status),
        focused: true,
      }));
  }, [stats]);

  const { totalLineData, cloudLineData, localLineData } = useMemo(() => {
    if (!stats?.timeSeries) return { totalLineData: [], cloudLineData: [], localLineData: [] };
    
    // Check data volume. If too many points > 200, maybe sample?
    // For now map all.
    let accTotal = 0;
    let accCloud = 0;
    let accLocal = 0;

    const total: any[] = [];
    const cloud: any[] = [];
    const local: any[] = [];

    stats.timeSeries.forEach((e) => {
        accTotal += e.total;
        accCloud += e.cloud;
        accLocal += e.local;

        // Reformat label if present
        let label = '';
        if (e.label) {
             const date = new Date(e.timestamp);
             const duration = (new Date(stats.timeSeries[stats.timeSeries.length-1].timestamp).getTime() - new Date(stats.timeSeries[0].timestamp).getTime());
            if (duration < 24 * 3600 * 1000) {
                label = date.toLocaleTimeString("en-GB", { hour: '2-digit', minute: '2-digit', hour12: false });
            } else {
                label = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
            }
        }

        total.push({ value: accTotal, label: label, dataPointText: '', timestamp: e.timestamp });
        cloud.push({ value: accCloud, label: label, dataPointText: '', timestamp: e.timestamp });
        local.push({ value: accLocal, label: label, dataPointText: '', timestamp: e.timestamp });
    });
    
    return { totalLineData: total, cloudLineData: cloud, localLineData: local };
  }, [stats]);

  const providerPieData = useMemo(() => {
    if (!stats) return [];
    return [
      { value: stats.totals.cloudRequests, color: CHART_PALETTE.cloud, text: 'Cloud' },
      { value: stats.totals.localRequests, color: CHART_PALETTE.local, text: 'Local' },
    ].filter(d => d.value > 0);
  }, [stats]);

  const modelPieData = useMemo(() => {
    const palette = [CHART_PALETTE.local, CHART_PALETTE.cloud, CHART_PALETTE.provider2, CHART_PALETTE.provider3, CHART_PALETTE.provider1];
    return (stats?.modelBreakdown ?? [])
     .slice(0, 5)
     .map((m, index) => ({
        value: m.requestCount,
        color: palette[index % palette.length],
        text: m.modelName,
     }));
  }, [stats]);

  const vramLineData = useMemo(() => {
    if (!stats?.timeSeries) return [];
    
    // Filter first to ensure step calculation is based on actual visible points
    const filtered = stats.timeSeries.filter(d => d.avgVram !== null);
    const step = Math.ceil(filtered.length / 10);

    return filtered.map((d, index) => ({
        value: d.avgVram!,
        label: index % step === 0 ? d.label : '',
    }));
  }, [stats]);

  return (
    <ScrollView
      className="w-full"
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      showsVerticalScrollIndicator={false}
    >
      <VStack className="w-full space-y-4">
        <Text size="2xl" className="font-bold text-center text-black dark:text-white">
          Statistics
        </Text>
        <Text className="text-center text-gray-500 dark:text-gray-300">
          Live insights from the request_events table: request volumes, timings, and health.
        </Text>

        {isUsingDemoData && (
          <Box className="w-full bg-amber-500/10 border border-amber-500/20 p-3 rounded-lg mb-4">
             <Text className="text-amber-500 text-center font-medium">
                Running in Demo Mode (Backend Unavailable)
             </Text>
          </Box>
        )}
        
        {loading || (!stats && (refreshing || isUsingDemoData)) ? (
          <VStack space="lg" className="items-center justify-center p-12">
            <ActivityIndicator size="large" color="#006DFF" />
            <Text className="text-gray-500">Loading statistics...</Text>
          </VStack>
        ) : stats ? (
          <VStack space="lg">
            <View className="w-full h-[1px] bg-outline-200 mt-12" />

            <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center', marginTop: 3, paddingHorizontal: 12 }}>
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
                    marginRight: 12,
                  }}
                >
                  <View className="flex-row items-center rounded-full bg-secondary-200 px-3 py-2 border border-outline-200">
                    <Text className="text-typography-900 text-sm mr-2">
                      {customRange ? formatRangeLabel(customRange) : ''}
                    </Text>
                    <Button
                      size="sm"
                      variant="outline"
                      action="negative"
                      onPress={handleClearCustomRange}
                      className="p-0 h-7 w-7 rounded-full"
                      accessibilityLabel="Clear selected range"
                    >
                      <ButtonIcon as={CloseIcon} className=" text-xs" />
                    </Button>
                  </View>
                </Animated.View>
              )}
              <Button
                size="sm"
                variant="solid"
                action="primary"
                className="rounded-full w-9 h-9 p-0 items-center justify-center text-typography-200"
                onPress={() => fetchStats()}
                accessibilityLabel="Refresh request statistics"
              >
                <ButtonIcon as={RotateCw} />
              </Button>
            </View>

            <ChartCard 
                title="Cumulative Request Volume (Total vs Cloud vs Local)"
                subtitle="Drag horizontally to zoom, Tap to inspect"
            >
              {(width) => (
                  <View>
                      {/* Legend */}
                      <View style={{ flexDirection: 'row', justifyContent: 'flex-start', marginBottom: 10, paddingHorizontal: 10 }}>
                          <View style={{ flexDirection: 'row', alignItems: 'center', marginRight: 16 }}>
                              <View style={{ width: 12, height: 12, borderRadius: 2, backgroundColor: CHART_PALETTE.total, marginRight: 6 }} />
                              <Text style={{ fontSize: 12, color: CHART_PALETTE.textLight }}>Total</Text>
                          </View>
                          <View style={{ flexDirection: 'row', alignItems: 'center', marginRight: 16 }}>
                              <View style={{ width: 12, height: 12, borderRadius: 2, backgroundColor: CHART_PALETTE.cloud, marginRight: 6 }} />
                              <Text style={{ fontSize: 12, color: CHART_PALETTE.textLight }}>Cloud</Text>
                          </View>
                          <View style={{ flexDirection: 'row', alignItems: 'center', marginRight: 16 }}>
                              <View style={{ width: 12, height: 12, borderRadius: 2, backgroundColor: CHART_PALETTE.local, marginRight: 6 }} />
                              <Text style={{ fontSize: 12, color: CHART_PALETTE.textLight }}>Local</Text>
                          </View>
                      </View>
                      
                      <InteractiveZoomableChart
                          width={width}
                          totalLineData={totalLineData}
                          cloudLineData={cloudLineData}
                          localLineData={localLineData}
                          timeWindow={timeWindow}
                          onZoom={setCustomRange}
                          colors={{ total: CHART_PALETTE.total, cloud: CHART_PALETTE.cloud, local: CHART_PALETTE.local }}
                      />
                  </View>
              )}
            </ChartCard>


            <HStack space="md" className="w-full">
                <View style={{ flex: 1 }}>
                    <ChartCard title="Request Type" className="flex-1">
                      {(width) => (
                        <View style={{ alignItems: 'center' }}>
                            <View style={{ alignItems: 'center', justifyContent: 'center' }}>
                                <PieChart
                                    data={providerPieData}
                                    donut
                                    innerRadius={width / 4}
                                    radius={width / 2.5}
                                    showText={false}
                                    textColor="white"
                                    textSize={12}
                                    showValuesAsLabels
                                    isAnimated={false}
                                    animationDuration={600}
                                    focusOnPress
                                    toggleFocusOnPress
                                />
                                <View 
                                    pointerEvents="none"
                                    className="absolute bg-secondary-200 rounded-full"
                                    style={{ width: width / 2, height: width / 2 }}
                                />
                            </View>
                            <VStack className="mt-4 space-y-1">
                                {providerPieData.map((d, i) => (
                                    <HStack key={i} space="xs" className="items-center">
                                        <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: d.color }} />
                                        <Text className="text-typography-700 text-xs">{d.text}: {d.value}</Text>
                                    </HStack>
                                ))}
                            </VStack>
                        </View>
                      )}
                    </ChartCard>
                </View>
                <View style={{ flex: 1 }}>
                    <ChartCard title="Model Share" className="flex-1">
                      {(width) => (
                        <View style={{ alignItems: 'center' }}>
                            <View style={{ alignItems: 'center', justifyContent: 'center' }}>
                                <PieChart
                                    data={modelPieData}
                                    donut
                                    innerRadius={width / 4}
                                    radius={width / 2.5}
                                    showText={false}
                                    isAnimated={false}
                                    animationDuration={600}
                                    focusOnPress
                                    toggleFocusOnPress
                                />
                                <View 
                                    pointerEvents="none"
                                    className="absolute bg-secondary-200 rounded-full"
                                    style={{ width: width / 2, height: width / 2 }}
                                />
                            </View>
                             <VStack className="mt-4 space-y-1">
                                {modelPieData.map((d, i) => (
                                    <HStack key={i} space="xs" className="items-center">
                                        <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: d.color }} />
                                        <Text className="text-typography-700 text-xs">{d.text}</Text>
                                    </HStack>
                                ))}
                            </VStack>
                        </View>
                      )}
                    </ChartCard>
                </View>
            </HStack>

            <View className="w-full h-[1px] bg-outline-200 my-12" />

            <ChartCard title="VRAM Remaining" subtitle="Per Ollama-Provider">
              {(width) => {
                const dayButtons = Array.from({ length: 7 }).map((_, idx) => {
                  const label =
                    idx === 0
                      ? 'Today'
                      : idx === 1
                        ? 'Yesterday'
                        : `${idx} days ago`;
                  const isActive = vramDayOffset === idx;
                  return (
                    <Button
                      key={idx}
                      size="sm"
                      variant={isActive ? "solid" : "outline"}
                      className="mr-2 mb-2"
                      onPress={() => setVramDayOffset(idx)}
                      accessibilityLabel={`Load VRAM for ${label}`}
                    >
                      <Text className={isActive ? "text-typography-200" : "text-typography-900"}>{label}</Text>
                    </Button>
                  );
                });

                const controls = (
                    <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 12 }}>
                      {dayButtons}
                      <Button
                        size="sm"
                        variant="solid"
                        action="primary"
                        className="rounded-full w-9 h-9 p-0 items-center justify-center mr-2 mb-2 text-typography-200"
                        onPress={() => fetchVramStats()}
                        accessibilityLabel="Refresh VRAM Stats"
                      >
                        <ButtonIcon as={RotateCw}/>
                      </Button>
                    </View>
                );

                if (isVramLoading) {
                    return (
                        <View>
                            {controls}
                            <View style={{height: 220, alignItems: 'center', justifyContent: 'center'}}>
                                <ActivityIndicator size="large" color="#006DFF" />
                            </View>
                        </View>
                    );
                }

                if (vramError) {
                  return (
                      <View>
                          {controls}
                          <EmptyState message={vramError} />
                      </View>
                  );
                }

                let providers = Object.keys(vramDataByProvider);
                const displayData = vramDataByProvider;
                if (providers.length === 0) {
                  return (
                    <View>
                      {controls}
                      <EmptyState message="No VRAM data available for the selected day." />
                    </View>
                  );
                }

                // Normal render
                return (
                  <View>
                    {controls}
                    {/* Legend */}
                    <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 16, paddingHorizontal: 8 }}>
                      {providers.map((url, index) => {
                         if (url === 'No Data') return null; 
                        const color = getProviderColor(index);
                        const shortUrl = url.replace("http://", "").split(":")[0];

                        return (
                          <View key={url} style={{ flexDirection: 'row', alignItems: 'center', marginRight: 16, marginBottom: 8 }}>
                            <View
                              style={{
                                width: 12,
                                height: 12,
                                backgroundColor: color,
                                borderRadius: 2,
                                marginRight: 6,
                              }}
                            />
                            <Text style={{ fontSize: 12, color: CHART_PALETTE.textLight }}>{shortUrl}</Text>
                          </View>
                        );
                      })}
                    </View>
                    

                    {/* Multi-line Chart */}
                    <ScrollView
                      horizontal
                      showsHorizontalScrollIndicator={true}
                      style={{ maxWidth: width - 32 }}
                      contentContainerStyle={{ paddingRight: 70, paddingLeft: 0 }}
                    >
                    {(() => {
                      const VRAM_SPACING = 1; // pixels per bucket
                      const bucketsPerHour = 3600 / vramBucketSizeSec;
                      const PIXELS_PER_HOUR = VRAM_SPACING * bucketsPerHour; 
                      
                      const yAxisLabelWidth = 38;
                      const initialSpacing = 0;
                      const endSpacing = 50;
                      
                      const totalBuckets = vramTotalBuckets || 8640;
                      const chartWidth = totalBuckets * VRAM_SPACING + initialSpacing + endSpacing;

                      const dataSet: any[] = [];
                      if (vramBaseline.length) {
                        dataSet.push({
                          data: vramBaseline,
                          color: 'transparent',
                          thickness: 0.0001,
                          hideDataPoints: true,
                          hidePointers: true,
                        });
                      }
                      providers.forEach((url, idx) => {
                        dataSet.push({
                            data: displayData[url] || [],
                            color: getProviderColor(idx),
                            thickness: 1.5,
                            hideDataPoints: true,
                            dataPointsRadius: 2,
                            dataPointsColor: getProviderColor(idx),
                            areaChart: true,
                            startFillColor: getProviderColor(idx),
                            endFillColor: getProviderColor(idx),
                            startOpacity: 0.3,
                            endOpacity: 0.1,
                        });
                      });
                      
                      // Manual Hour Labels 
                      const hourLabels = [];
                      for(let h=0; h<=24; h++) {
                          hourLabels.push({
                              time: `${h}:00`,
                              x: initialSpacing + h * PIXELS_PER_HOUR
                          });
                      }

                      // Calculate "now" position if viewing today (in UTC)
                      const now = new Date();
                      const isToday = vramDayOffset === 0;
                      let nowXPosition: number | null = null;

                      if (isToday) {
                        const nowMs = now.getTime();
                        const todayUtc = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
                        const todayStartMs = todayUtc.getTime();
                        
                        const diffSec = (nowMs - todayStartMs) / 1000;
                        if (diffSec >= 0 && diffSec <= 86400) {
                            const bucketsFromStart = diffSec / vramBucketSizeSec;
                            nowXPosition = initialSpacing + bucketsFromStart * VRAM_SPACING;
                        }
                      }

                      return (
                        <View style={{ position: 'relative', paddingBottom: 40 }}>
                          <LineChart
                            key={`vram-${vramDayOffset}-${Object.keys(displayData).length}-${Object.values(displayData).map(d => d.length).reduce((a, b) => a + b, 0)}`}
                            isAnimated={true}
                            dataSet={dataSet}
                            height={220}
                            adjustToWidth={false}
                            width={chartWidth}
                            initialSpacing={initialSpacing}
                            endSpacing={endSpacing}
                            spacing={VRAM_SPACING}
                            yAxisThickness={0}
                            yAxisLabelWidth={yAxisLabelWidth}
                            xAxisThickness={1}
                            xAxisColor="#334155"
                            yAxisTextStyle={{ color: CHART_PALETTE.textLight, fontSize: 10, top: 4 }}
                            hideAxesAndRules={false}
                            rulesType="dashed"
                            rulesColor="#334155"
                            dashWidth={4}
                            dashGap={4}
                            noOfSections={5}
                            yAxisLabelSuffix=" GB"
                            xAxisLabelsHeight={0}
                            pointerConfig={{
                            pointerStripHeight: 220,
                            pointerStripColor: CHART_PALETTE.textLight,
                            pointerStripWidth: 1,
                            pointerColor: CHART_PALETTE.provider1,
                            radius: 4,
                            pointerLabelWidth: 160,
                            pointerLabelHeight: 110,
                            activatePointersOnLongPress: false,
                            autoAdjustPointerLabelPosition: true,
                            pointerLabelComponent: (items: any) => {
                              const providerItems = (items || [])
                                .filter((item: any) => item && !item._empty && !item._isBaseline);
                              
                              const anyItem = (items||[])[0];
                              const ts = anyItem?.timestamp;
                              const labelText = ts 
                                ? new Date(ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: 'UTC' })
                                : (anyItem?.label || '');

                              return (
                                <View
                                  style={{
                                    backgroundColor: '#1f2937',
                                    padding: 8,
                                    borderRadius: 8,
                                    borderWidth: 1,
                                    borderColor: '#374151',
                                  }}
                                >
                                  <Text style={{ color: '#9ca3af', fontSize: 10, marginBottom: 4 }}>
                                    {labelText}
                                  </Text>
                                  {providerItems.length === 0 ? (
                                    <Text style={{ color: '#ef4444', fontSize: 10, fontWeight: '600' }}>
                                      No connection to the server
                                    </Text>
                                  ) : (
                                    providerItems.map((item: any, index: number) => {
                                    return (
                                      <View key={index} style={{ marginTop: 6 }}>
                                        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                                            <View
                                            style={{
                                                width: 8,
                                                height: 8,
                                                backgroundColor: item.dataPointsColor || 'gray',
                                                borderRadius: 2,
                                                marginRight: 6,
                                            }}
                                            />
                                            <View>
                                            <Text style={{ color: 'white', fontSize: 10 }}>
                                                {item.remaining_vram_gb} GB free
                                            </Text>
                                            <Text style={{ color: '#e2e8f0', fontSize: 10 }}>
                                                Used: {item.used_vram_gb} GB
                                            </Text>
                                            </View>
                                        </View>
                                        {/* Loaded Models */}
                                        {item.loaded_model_names && item.loaded_model_names.length > 0 && (
                                            <View style={{ marginTop: 4, paddingLeft: 14 }}>
                                                {item.loaded_model_names.map((name: string, mIdx: number) => (
                                                    <Text key={mIdx} style={{ color: '#F29C6E', fontSize: 9 }}>
                                                        • {name}
                                                    </Text>
                                                ))}
                                            </View>
                                        )}
                                      </View>
                                    );
                                  })
                                  )}
                                </View>
                              );
                            },
                          }}
                          interpolateMissingValues={false}
                        />
                        {/* "Now" indicator line */}
                        {nowXPosition !== null && (
                          <View
                            style={{
                              position: 'absolute',
                              left: Math.max((nowXPosition ?? 0) - 1, 0),
                              top: 0,
                              bottom: 0,
                              width: 1,
                              borderStyle: 'dashed',
                              borderWidth: 1,
                              borderColor: '#ef4444',
                              zIndex: 10,
                              pointerEvents: 'none',
                            }}
                          >
                            <View style={{position: 'absolute', top: -16, left: -14, backgroundColor: '#ef4444', paddingHorizontal: 4, borderRadius: 4}}>
                              <Text style={{color: 'white', fontSize: 9, fontWeight: 'bold'}}>NOW</Text>
                            </View>
                          </View>
                        )}
                        {/* Custom X Axis Labels */}
                        <View style={{ position: 'absolute', bottom: 5, left: 0, right: 0, height: 30 }}>
                             {hourLabels.map((lbl, i) => (
                                 <Text key={i} style={{ 
                                     position: 'absolute', 
                                     left: lbl.x - 10, 
                                     color: CHART_PALETTE.textLight, 
                                     fontSize: 10 
                                  }}>
                                     {lbl.time}
                                 </Text>
                             ))}
                        </View>
                      </View>
                    );
                    })()}
                    </ScrollView>
                  </View>
                );
              }}
            </ChartCard>
          </VStack>
        ) : (
          <Text className="text-center text-red-500">{error || 'Unable to load statistics.'}</Text>
        )}
      </VStack>
    </ScrollView>
  );
}


type SelectionState = {
  start: number;
  end: number;
  active: boolean;
  pageX?: number;
  confirmable?: boolean;
};

const InteractiveZoomableChart = ({ 
  width, 
  totalLineData, 
  cloudLineData, 
  localLineData, 
  timeWindow, 
  onZoom,
  colors
}: { 
  width: number; 
  totalLineData: any[]; 
  cloudLineData: any[]; 
  localLineData: any[]; 
  timeWindow: string;
  onZoom: (range: { start: Date; end: Date }) => void;
  colors: { total: string; cloud: string; local: string };
}) => {
    const [selection, setSelection] = useState<SelectionState | null>(null);
    const selectionRef = useRef<SelectionState | null>(null);
    const containerRef = useRef<View | null>(null);
    const confirmAnim = useRef(new Animated.Value(0)).current;
    const chartWidth = width - 20;
    const chartHeight = 250; // Match LineChart height
    const clampX = useCallback((x: number) => Math.max(0, Math.min(chartWidth, x)), [chartWidth]);

    // Calculate dynamic spacing to fill the width
    const dataLength = totalLineData.length;
    const spacing = dataLength > 1 ? chartWidth / (dataLength - 1) : chartWidth;

    // Helper: Map x in chart-space to timestamp
    const getTimestampFromX = useCallback((x: number) => {
        if (!totalLineData.length) return 0;
        const firstTs = totalLineData[0].timestamp;
        const lastTs = totalLineData[totalLineData.length - 1].timestamp;
        const duration = lastTs - firstTs;
        const pct = Math.max(0, Math.min(1, clampX(x) / chartWidth));
        return firstTs + pct * duration;
    }, [totalLineData, chartWidth, clampX]);

    const confirmSelection = useCallback(() => {
        if (!selection || !selection.confirmable) return;
        const startX = Math.min(selection.start, selection.end);
        const endX = Math.max(selection.start, selection.end);
        const startTs = getTimestampFromX(startX);
        const endTs = getTimestampFromX(endX);

        setSelection(null);
        selectionRef.current = null;
        onZoom({ start: new Date(startTs), end: new Date(endTs) });
    }, [selection, getTimestampFromX, onZoom]);

    useEffect(() => {
        if (selection?.confirmable) {
            confirmAnim.setValue(0);
            Animated.timing(confirmAnim, {
                toValue: 1,
                duration: 100,
                easing: Easing.out(Easing.quad),
                useNativeDriver: true,
            }).start();
        } else {
            confirmAnim.setValue(0);
        }
    }, [selection?.confirmable, confirmAnim]);

    const panResponder = useMemo(() => PanResponder.create({
        // Capture horizontal drags (differentiate from vertical scroll)
        onMoveShouldSetPanResponderCapture: (_, gestureState) => {
            return Math.abs(gestureState.dx) > 5 && Math.abs(gestureState.dy) < Math.abs(gestureState.dx);
        },
        
        onPanResponderGrant: (_evt, gestureState) => {
             // Measure relative to page to be robust against child targets (web issue)
             containerRef.current?.measure((_x, _y, _w, _h, pageX, _pageY) => {
                 const localStart = clampX(gestureState.x0 - pageX);
                 const newSel: SelectionState = { start: localStart, end: localStart, active: true, pageX, confirmable: false };
                 selectionRef.current = newSel;
                 setSelection({ ...newSel });
             });
        },

        onPanResponderMove: (_evt, gestureState) => {
            const sel = selectionRef.current;
            if (!sel) return;
            
            // Calculate new end based on moveX and captured pageX
            let localEnd = clampX(gestureState.moveX - (sel.pageX || 0));
            
            // update ref
            sel.end = localEnd;
            sel.confirmable = false;
            // update state for render
            setSelection({ start: sel.start, end: localEnd, active: true });
        },

        onPanResponderRelease: () => {
             const sel = selectionRef.current;
             if (sel && Math.abs(sel.end - sel.start) > 20) {
                 const startX = clampX(Math.min(sel.start, sel.end));
                 const endX = clampX(Math.max(sel.start, sel.end));
                 
                 const finalized: SelectionState = { start: startX, end: endX, active: false, confirmable: true };
                 selectionRef.current = finalized;
                 setSelection(finalized);
             } else {
                 setSelection(null);
                 selectionRef.current = null;
             }
        },
        onPanResponderTerminate: () => {
            setSelection(null);
            selectionRef.current = null;
        },
   }), [clampX]); 

   return totalLineData.length ? (
    <View 
        ref={containerRef}
        {...panResponder.panHandlers} 
        className="web:select-none"
        style={{ position: 'relative', width: width, height: 340, justifyContent: 'center', backgroundColor: 'transparent', userSelect: 'none' as any }}
    >
     {selection ? (
         <View 
             pointerEvents="box-none"
             style={{
                 position: 'absolute',
                 left: Math.min(selection.start, selection.end),
                 width: Math.abs(selection.end - selection.start),
                 top: 0,
                 bottom: 20, 
                 zIndex: 999, 
             }}
         >
            <View
              pointerEvents="none"
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                top: 0,
                bottom: 0,
                backgroundColor: 'rgba(59, 233, 222, 0.3)', 
                borderWidth: 1,
                borderColor: '#3BE9DE',
              }}
            />
            {selection.confirmable && (
              <Animated.View
                style={{
                  alignItems: 'center',
                  paddingTop: 8,
                  opacity: confirmAnim,
                  transform: [
                    {
                      scale: confirmAnim.interpolate({
                        inputRange: [0, 1],
                        outputRange: [0.95, 1],
                      }),
                    },
                  ],
                }}
              >
                <Button
                  size="sm"
                  action="positive"
                  onPress={confirmSelection}
                  className="shadow-hard-1 h-12 w-12 rounded-full"
                  accessibilityLabel="Apply zoom"
                >
                  <ButtonIcon as={CheckIcon} className="text-white h-6 w-6" />
                </Button>
              </Animated.View>
            )}
         </View>
     ) : null}
    <View pointerEvents={selection?.active ? 'none' : 'auto'}> 
    <LineChart
      isAnimated={true}
      key={totalLineData.length ? `${totalLineData[0].timestamp}-${totalLineData[totalLineData.length - 1].timestamp}` : 'chart'}
      height={chartHeight}
      data={totalLineData}
      data2={cloudLineData}
      data3={localLineData}
      disableScroll
      adjustToWidth
      hideDataPoints
      width={width - 50} // Increased padding to prevent right-side cutoff
      thickness={3}
      color1={colors.total}
      color2={colors.cloud}
      thickness2={3}
      color3={colors.local}
      thickness3={3}
      rulesType="dashed"
      rulesColor="#525252"
      yAxisThickness={0}
      xAxisType="dashed"
      xAxisColor="#525252"
      yAxisTextStyle={{ color: '#64748B', top: 4 }} // Slate-500
      xAxisLabelTextStyle={{ color: '#64748B', width: 60 }}   // Slate-500
      xAxisTextNumberOfLines={2}
      xAxisLabelsVerticalShift={20}
      labelsExtraHeight={20}
      noOfSections={5}
      curved
      areaChart
      startFillColor1={colors.total}
      endFillColor1={colors.total}
      startOpacity1={0.3}
      endOpacity1={0.1}
      
      startFillColor2={colors.cloud}
      endFillColor2={colors.cloud}
      startOpacity2={0.3}
      endOpacity2={0.1}
      
      startFillColor3={colors.local}
      endFillColor3={colors.local}
      startOpacity3={0.3}
      endOpacity3={0.1}
    />
    </View>
    </View>
  ) : (
    <EmptyState message="No timeline data available." />
  );
}

const ChartCard = ({ title, subtitle, children, className }: { title: string; subtitle?: string; children: (width: number) => React.ReactNode; className?: string }) => {
  const [layoutWidth, setLayoutWidth] = useState(0);

  return (
    <View
      className={`bg-secondary-200 rounded-2xl p-4 my-2.5 shadow-hard-2 ${className || ''}`}
      onLayout={(e) => {
        const w = e.nativeEvent.layout.width;
        if (Math.abs(w - layoutWidth) > 1) setLayoutWidth(w);
      }}
    >
      <View className="mb-5">
        <Text className="text-lg font-semibold text-typography-900">{title}</Text>
        {subtitle && <Text className="text-xs text-typography-600 mt-1">{subtitle}</Text>}
      </View>
      {layoutWidth > 0 ? (
        children(layoutWidth - 32)
      ) : (
        <View style={{ height: 200 }} />
      )}
    </View>
  );
};


const EmptyState = ({ message }: { message: string }) => (
  <Box className="p-4 rounded-lg bg-background-100 border border-dashed border-outline-300">
    <Text className="text-typography-500 text-center">{message}</Text>
  </Box>
);
