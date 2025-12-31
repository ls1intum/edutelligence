import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Easing, PanResponder, Platform, RefreshControl, ScrollView, View } from 'react-native';
import { LineChart, PieChart } from 'react-native-gifted-charts';

import { useAuth } from '@/components/auth-shell';
import { Box } from "@/components/ui/box";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import { Button, ButtonIcon } from "@/components/ui/button";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { CheckIcon, CloseIcon } from '@/components/ui/icon';

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

type RequestEventResponse = { rows: RequestEventRow[] };

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

export default function Statistics() {
  const { apiKey } = useAuth();
  
  // State
  const timeWindow: '30d' = '30d';
  const [customRange, setCustomRange] = useState<{ start: Date; end: Date } | null>(null);
  const [showRangeBadge, setShowRangeBadge] = useState(false);
  const rangeBadgeAnim = useRef(new Animated.Value(0)).current;
  
  // Data
  const [allRows, setAllRows] = useState<RequestEventRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Compute filtered rows
  const filteredRows = useMemo(() => {
    if (!allRows.length) return [];
    
    // 1. Determine base cutoff
    const now = new Date();
    let cutoff = new Date();
    if (timeWindow === '30d') cutoff.setDate(now.getDate() - 30);
    else if (timeWindow === '7d') cutoff.setDate(now.getDate() - 7);
    else if (timeWindow === '24h') cutoff.setHours(now.getHours() - 24);
    
    // 2. Apply Custom Range Zoom if active (override window or refine it?)
    // Usually zoom is within the window. Let's say filter first by window, then by range.
    // Or range implies specific filtered view.
    // Let's filter by window first.
    let rows = allRows.filter(r => r.enqueue_ts && new Date(r.enqueue_ts) >= cutoff);

    if (customRange) {
        rows = rows.filter(r => {
            if (!r.enqueue_ts) return false;
            const t = new Date(r.enqueue_ts);
            return t >= customRange.start && t <= customRange.end;
        });
    }
    return rows;
  }, [allRows, timeWindow, customRange]);

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
    const now = Date.now();
    let bucketMs = 3600 * 1000; // default 1h
    if (timeWindow === '30d') bucketMs = 24 * 3600 * 1000; // 1 day
    else if (timeWindow === '7d') bucketMs = 4 * 3600 * 1000; // 4 hours
    else if (timeWindow === '24h') bucketMs = 30 * 60 * 1000; // 30 min

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
        const date = new Date(ts);
        let label = '';
        if (timeWindow === '24h') label = `${date.getHours()}:${date.getMinutes().toString().padStart(2, '0')}`;
        else if (timeWindow === '7d') label = `${date.getDate()}/${date.getMonth()+1} ${date.getHours()}h`;
        else label = `${date.getDate()}/${date.getMonth()+1}`;
        
        return {
            timestamp: ts,
            label,
            cloud: data.cloud,
            local: data.local,
            total: data.cloud + data.local,
            avgRunSeconds: avg(data.run),
            avgVram: avg(data.vram)
        };
      })
      .sort((a, b) => a.timestamp - b.timestamp);

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
  }, [timeWindow]);

  const stats = useMemo(() => computeStats(filteredRows), [computeStats, filteredRows]);

  const fetchStats = useCallback(async () => {
    if (!apiKey) {
        // use mock data immediately if no key provided?
        // or just wait. 
        // For debugging we can use mock data if apiKey is missing too
        setAllRows(MOCK_RESPONSE.rows);
        setLoading(false);
        return;
    }
    setRefreshing(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/logosdb/request_event_stats`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'logos_key': apiKey,
          'Authorization': `Bearer ${apiKey}`,
        },
        body: JSON.stringify({ logos_key: apiKey }),
      });
      if (!response.ok) {
        throw new Error(`Status ${response.status}`);
      }
      const data: RequestEventResponse = await response.json();
      setAllRows(data.rows);
    } catch (err) {
      console.error('[Statistics] failed to load stats', err);
      // Fallback to mock data for local troubleshooting
      setAllRows(MOCK_RESPONSE.rows);
      setError(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiKey]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

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

    const step = Math.ceil(stats.timeSeries.length / 10);

    stats.timeSeries.forEach((e, index) => {
        accTotal += e.total;
        accCloud += e.cloud;
        accLocal += e.local;

        const label = index % step === 0 ? e.label : '';

        total.push({ value: accTotal, label, dataPointText: '', timestamp: e.timestamp });
        cloud.push({ value: accCloud, label, dataPointText: '', timestamp: e.timestamp });
        local.push({ value: accLocal, label, dataPointText: '', timestamp: e.timestamp });
    });
    
    return { totalLineData: total, cloudLineData: cloud, localLineData: local };
  }, [stats]);

  const providerPieData = useMemo(() => {
    if (!stats) return [];
    return [
      { value: stats.totals.cloudRequests, color: '#3BE9DE', text: 'Cloud' },
      { value: stats.totals.localRequests, color: '#006DFF', text: 'Local' },
    ].filter(d => d.value > 0);
  }, [stats]);

  const modelPieData = useMemo(() => {
    return (stats?.modelBreakdown ?? [])
     .slice(0, 5)
     .map((m, index) => ({
        value: m.requestCount,
        color: index % 2 === 0 ? '#006DFF' : '#3BE9DE',
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
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={fetchStats} />}
    >
      <VStack className="w-full space-y-4">
        <Text size="2xl" className="font-bold text-center text-black dark:text-white">
          Statistics
        </Text>
        <Text className="text-center text-gray-500 dark:text-gray-300">
          Live insights from the request_events table: request volumes, timings, and health.
        </Text>

        {loading ? (
          <VStack space="lg">
            <HStack space="md" className="justify-center">
              {Array.from({ length: 3 }).map((_, idx) => (
                <Skeleton key={idx} className="h-[90px] w-[120px] rounded-xl bg-background-200" variant="rounded" />
              ))}
            </HStack>
            <Box className="p-4 rounded-2xl border border-outline-200 bg-background-50">
              <SkeletonText _lines={3} className="h-3 bg-background-200 rounded-md" />
            </Box>
          </VStack>
        ) : stats ? (
          <VStack space="lg">
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
                <HStack className="justify-center">
                  <View className="flex-row items-center rounded-full bg-secondary-200 px-3 py-2 border border-outline-200">
                    <Text className="text-typography-900 text-sm mr-2">
                      {customRange ? formatRangeLabel(customRange) : ''}
                    </Text>
                    <Button
                      size="sm"
                      variant="outline"
                      action="negative"
                      onPress={() => setCustomRange(null)}
                      className="p-0 h-7 w-7 rounded-full"
                      accessibilityLabel="Clear selected range"
                    >
                      <ButtonIcon as={CloseIcon} className=" text-xs" />
                    </Button>
                  </View>
                </HStack>
              </Animated.View>
            )}

            <ChartCard 
                title="Cumulative Request Volume (Total vs Cloud vs Local)"
                subtitle="Drag horizontally to zoom, Tap to inspect"
            >
              {(width) => (
                  <InteractiveZoomableChart
                      width={width}
                      totalLineData={totalLineData}
                      cloudLineData={cloudLineData}
                      localLineData={localLineData}
                      timeWindow={timeWindow}
                      onZoom={setCustomRange}
                  />
              )}
            </ChartCard>


            <HStack space="md" className="w-full">
                <View style={{ flex: 1 }}>
                    <ChartCard title="Request Type">
                      {(width) => (
                        <View style={{ alignItems: 'center' }}>
                            <PieChart
                                data={providerPieData}
                                donut
                                innerRadius={width / 4}
                                radius={width / 2.5}
                                showText
                                textColor="white"
                                textSize={12}
                                showValuesAsLabels
                                isAnimated
                                animationDuration={600}
                                focusOnPress
                                toggleFocusOnPress
                            />
                            <VStack className="mt-4 space-y-1">
                                {providerPieData.map((d, i) => (
                                    <HStack key={i} space="xs" className="items-center">
                                        <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: d.color }} />
                                        <Text className="text-gray-300 text-xs">{d.text}: {d.value}</Text>
                                    </HStack>
                                ))}
                            </VStack>
                        </View>
                      )}
                    </ChartCard>
                </View>
                <View style={{ flex: 1 }}>
                    <ChartCard title="Model Share">
                      {(width) => (
                        <View style={{ alignItems: 'center' }}>
                            <PieChart
                                data={modelPieData}
                                donut
                                innerRadius={width / 4}
                                radius={width / 2.5}
                                showText={false}
                                isAnimated
                                animationDuration={600}
                                focusOnPress
                                toggleFocusOnPress
                            />
                             <VStack className="mt-4 space-y-1">
                                {modelPieData.map((d, i) => (
                                    <HStack key={i} space="xs" className="items-center">
                                        <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: d.color }} />
                                        <Text className="text-gray-300 text-xs">{d.text}</Text>
                                    </HStack>
                                ))}
                            </VStack>
                        </View>
                      )}
                    </ChartCard>
                </View>
            </HStack>

            <ChartCard title="Resource Usage (VRAM)">
              {(width) => (
                <LineChart
                    data={vramLineData}
                    width={width - 20}
                    thickness={3}
                    color="#F29C6E"
                    startFillColor="#F29C6E"
                    endFillColor="#F29C6E"
                    startOpacity={0.2}
                    endOpacity={0.0}
                    areaChart
                    curved
                    rulesType="dashed"
                    rulesColor="#525252"
                    yAxisThickness={0}
                    xAxisType="dashed"
                    xAxisColor="#525252"
                    yAxisTextStyle={{ color: '#A3A3A3', fontWeight: '500', top: 4 }}
                    xAxisLabelTextStyle={{ color: '#A3A3A3' }}
                    noOfSections={5}
                    isAnimated
                    animationDuration={600}
                    animateOnDataChange
                    pointerConfig={{
                      pointerStripUptoDataPoint: true,
                      pointerStripColor: 'rgba(255, 255, 255, 0.2)',
                      pointerStripWidth: 2,
                      pointerColor: 'white',
                      radius: 6,
                      pointerLabelWidth: 100,
                      pointerLabelHeight: 90,
                      activatePointersOnLongPress: false,
                      autoAdjustPointerLabelPosition: true,
                      pointerLabelComponent: (items: any) => {
                        const item = items[0];
                        return (
                          <View
                            style={{
                              width: 100,
                              justifyContent: 'center',
                              alignItems: 'center',
                              backgroundColor: '#1f2937',
                              borderRadius: 8,
                              padding: 8,
                            }}
                          >
                            <Text style={{ color: '#9ca3af', fontSize: 10, marginBottom: 4 }}>{item.label}</Text>
                            <Text style={{ color: 'white', fontWeight: 'bold' }}>{Math.round(item.value)} MB</Text>
                          </View>
                        );
                      },
                    }}
                />
              )}
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
  onZoom 
}: { 
  width: number; 
  totalLineData: any[]; 
  cloudLineData: any[]; 
  localLineData: any[]; 
  timeWindow: string;
  onZoom: (range: { start: Date; end: Date }) => void;
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
      key={totalLineData.length ? `${totalLineData[0].timestamp}-${totalLineData[totalLineData.length - 1].timestamp}` : 'chart'}
      height={chartHeight}
      data={totalLineData}
      data2={cloudLineData}
      data3={localLineData}
      spacing={spacing}
      initialSpacing={0}
      endSpacing={0}
      hideDataPoints
      width={width - 20}
      thickness={3}
      color1="#9ca3af" // gray-400
      color2="#3BE9DE"
      thickness2={3}
      color3="#006DFF"
      thickness3={3}
      curved
      rulesType="dashed"
      rulesColor="#525252"
      yAxisThickness={0}
      xAxisType="dashed"
      xAxisColor="#525252"
      yAxisTextStyle={{ color: '#A3A3A3', top: 4 }}
      xAxisLabelTextStyle={{ color: '#A3A3A3' }}
      xAxisLabelsVerticalShift={20}
      labelsExtraHeight={20}
      noOfSections={5}
      showScrollIndicator
      isAnimated={false}
    />
    </View>
    </View>
  ) : (
    <EmptyState message="No timeline data available." />
  );
}

const ChartCard = ({ title, subtitle, children }: { title: string; subtitle?: string; children: (width: number) => React.ReactNode }) => {
  const [layoutWidth, setLayoutWidth] = useState(0);

  return (
    <View
      className="bg-secondary-200 rounded-2xl p-4 my-2.5 shadow-hard-2"
      onLayout={(e) => setLayoutWidth(e.nativeEvent.layout.width)}
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
