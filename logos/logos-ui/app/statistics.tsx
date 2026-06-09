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
  Platform,
  Pressable,
  View,
} from "react-native";
import { PieChart } from "react-native-gifted-charts";
import Svg, { Polyline } from "react-native-svg";
import { RotateCw } from "lucide-react-native";

import { useAuth } from "@/components/auth-shell";
import PlotlyPieChart from "@/components/statistics/plotly-pie-chart";
import { Text } from "@/components/ui/text";
import { VStack } from "@/components/ui/vstack";
import { HStack } from "@/components/ui/hstack";
import {
  Select,
  SelectBackdrop,
  SelectContent,
  SelectInput,
  SelectItem,
  SelectPortal,
  SelectTrigger,
} from "@/components/ui/select";
import { Button, ButtonIcon } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CloseIcon } from "@/components/ui/icon";
import type { RequestLogStats, DeviceInfo, LaneSignalData } from "@/components/statistics/types";
import ChartCard from "@/components/statistics/chart-card";
import EmptyState from "@/components/statistics/empty-state";
import InteractiveZoomableChart from "@/components/statistics/interactive-zoomable-chart";
import VramChart from "@/components/statistics/vram-chart";
import PlotlyVramChart from "@/components/statistics/plotly-vram-chart";
import PlotlyRequestVolumeChart from "@/components/statistics/plotly-request-volume-chart";
import WorkerGpuPanel from "@/components/statistics/worker-gpu-panel";
import LaneMetricsPanel from "@/components/statistics/lane-metrics-panel";
import PaginatedRequestList from "@/components/statistics/paginated-request-list";
import LaneVramPie from "@/components/statistics/lane-vram-pie";
import {
  API_BASE,
  CHART_PALETTE,
  MODEL_PALETTE,
  getLaneStateColor,
  getProviderColor,
} from "@/components/statistics/constants";
import {
  formatRangeLabel,
  applyTimeSeriesLabels,
  calculateDateRange,
} from "@/lib/utils/statistics";
import type { RequestItem } from "@/components/statistics/request-stack";
import {
  useStatsWebSocketV2,
  VramV2Payload,
  VramV2Sample,
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

type VramProviderMeta = {
  provider_id?: number;
  connected?: boolean;
  connection_state?: string;
  provider_type?: string;
  runtime_modes?: string[];
  transport_connected?: boolean;
  last_heartbeat?: string | null;
};

type VramProviderPayload = {
  provider_id: number;
  name: string;
  data: Array<any>;
  connected?: boolean;
  connection_state?: string;
  provider_type?: string;
  runtime_modes?: string[];
  transport_connected?: boolean;
  last_heartbeat?: string | null;
};

const buildVramSignature = (
  providers: VramProviderPayload[]
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
        provider.connection_state ?? "",
        (provider.runtime_modes || []).join("|"),
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

const getLoadedModelSizeBytes = (model: any): number => {
  if (typeof model?.size_vram === "number" && model.size_vram > 0) {
    return model.size_vram;
  }
  if (typeof model?.size_vram_mb === "number" && model.size_vram_mb > 0) {
    return model.size_vram_mb * BYTES_PER_MIB;
  }
  if (typeof model?.size === "number" && model.size > 0) {
    return model.size;
  }
  if (typeof model?.size_mb === "number" && model.size_mb > 0) {
    return model.size_mb * BYTES_PER_MIB;
  }
  return 0;
};

const getLoadedModelsFromRaw = (
  raw: any
): Array<{ name: string; size_gb: number }> =>
  (raw?.loaded_models || [])
    .map((m: any) => {
      const sizeBytes = getLoadedModelSizeBytes(m);
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

  // Prefer the reported hardware total; `used + remaining` mixes two accounting systems.
  const totalBytes = configuredTotalBytes > 0 ? configuredTotalBytes : usedBytes + remainingBytes;

  return {
    usedGb: toDecimalGb(usedBytes),
    remainingGb: toDecimalGb(remainingBytes),
    totalGb: toDecimalGb(totalBytes),
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

/**
 * Single source of truth for a sample's VRAM in MB. Prefers the authoritative
 * nvidia-smi figures (scheduler_signals.provider), falling back to the legacy
 * top-level fields. Used for both per-provider and all-provider summaries.
 */
const extractProviderVramMb = (
  sample: VramV2Sample | null | undefined
): { totalMb: number; usedMb: number; freeMb: number } => {
  const prov = sample?.scheduler_signals?.provider;
  const totalMb = prov?.total_memory_mb ?? sample?.total_vram_mb ?? 0;
  const freeMb = prov?.free_memory_mb ?? sample?.remaining_vram_mb ?? 0;
  const usedMb = prov?.used_memory_mb ?? Math.max(0, totalMb - freeMb);
  return { totalMb, usedMb, freeMb };
};

/* ── Skeletons ──────────────────────────────────────────────── *
 * One skeleton per visible card. Each mirrors the real card's
 * layout 1:1 (same outer chrome, same proportions, same column
 * structure) so the page doesn't reflow when data lands. The
 * gating is granular: each card flips from skeleton to real
 * content as soon as *its* data is ready, instead of waiting on
 * a single top-level "everything resolved" flag.
 */

const SKELETON_START_COLOR = "bg-background-200";

function SkeletonBar({
  width,
  height,
  className,
  rounded,
}: {
  width: number | string;
  height: number;
  className?: string;
  rounded?: number;
}) {
  return (
    <Skeleton
      variant="rounded"
      startColor={SKELETON_START_COLOR}
      className={className}
      style={{
        width: width as any,
        height,
        borderRadius: rounded ?? 6,
      }}
    />
  );
}

function SkeletonDot({ size = 8 }: { size?: number }) {
  return (
    <Skeleton
      variant="circular"
      startColor={SKELETON_START_COLOR}
      style={{ width: size, height: size }}
    />
  );
}

/** KPI card skeleton — matches `KpiCard` chrome and three-row layout. */
function KpiCardSkeleton() {
  return (
    <View
      className="rounded-2xl border border-outline-200 bg-background-0 shadow-soft-1"
      style={{
        flexBasis: "calc(25% - 9px)" as any,
        flexGrow: 0,
        flexShrink: 1,
        minWidth: 200,
        alignSelf: "stretch",
        paddingTop: 14,
        paddingBottom: 14,
        paddingLeft: 18,
        paddingRight: 18,
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Row 1: dot + label */}
      <View
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          columnGap: 8,
        }}
      >
        <SkeletonDot size={6} />
        <SkeletonBar width={80} height={10} rounded={3} />
      </View>
      {/* Row 2: big number + sparkline placeholder */}
      <View
        style={{
          marginTop: 8,
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          columnGap: 12,
        }}
      >
        <SkeletonBar width={88} height={28} />
        <SkeletonBar width={92} height={20} />
      </View>
      {/* Row 3: hint */}
      <View style={{ marginTop: 10 }}>
        <SkeletonBar width="78%" height={11} rounded={3} />
      </View>
    </View>
  );
}

/** Donut + bottom legend skeleton (used for VRAM utilisation, Request type, Model share). */
function DonutSkeleton({
  diameter = 180,
  legendItems = 3,
  centerRows = 2,
}: {
  diameter?: number;
  legendItems?: number;
  centerRows?: number;
}) {
  const inner = Math.round(diameter * 0.55);
  return (
    <View style={{ alignItems: "center", width: "100%" }}>
      <View
        style={{
          width: diameter,
          height: diameter,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Skeleton
          variant="circular"
          startColor={SKELETON_START_COLOR}
          style={{ width: diameter, height: diameter, position: "absolute" }}
        />
        {/* Hole that punches the donut */}
        <View
          className="bg-background-0"
          style={{
            width: inner,
            height: inner,
            borderRadius: inner / 2,
            alignItems: "center",
            justifyContent: "center",
            rowGap: 6,
          }}
        >
          {centerRows >= 1 ? <SkeletonBar width={28} height={8} rounded={3} /> : null}
          {centerRows >= 2 ? <SkeletonBar width={48} height={16} /> : null}
          {centerRows >= 3 ? <SkeletonBar width={40} height={8} rounded={3} /> : null}
        </View>
      </View>
      {/* Legend rows under the donut */}
      <View style={{ marginTop: 14, rowGap: 8, width: "100%", alignItems: "center" }}>
        {Array.from({ length: legendItems }).map((_, idx) => (
          <View
            key={idx}
            style={{
              flexDirection: "row",
              alignItems: "center",
              columnGap: 8,
            }}
          >
            <SkeletonDot size={9} />
            <SkeletonBar width={140 - idx * 10} height={9} rounded={3} />
          </View>
        ))}
      </View>
    </View>
  );
}

/** Bar-chart skeleton for the volume card. */
function BarChartSkeleton({ height = 320 }: { height?: number }) {
  // Heights mimic bursty traffic: a couple tall bars + many shorter ones.
  const bars = [
    0.12, 0.22, 0.18, 0.30, 0.55, 0.84, 0.96, 0.62, 0.40, 0.28,
    0.18, 0.10, 0.14, 0.22, 0.30, 0.46, 0.20, 0.12, 0.08, 0.16,
    0.24, 0.44, 0.36, 0.22, 0.14,
  ];
  return (
    <View style={{ width: "100%" }}>
      {/* Segmented switch placeholder + legend dots */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          columnGap: 12,
          marginBottom: 10,
        }}
      >
        <SkeletonBar width={172} height={28} rounded={999} />
        <View style={{ flexDirection: "row", alignItems: "center", columnGap: 6 }}>
          <SkeletonDot size={8} />
          <SkeletonBar width={36} height={8} rounded={3} />
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", columnGap: 6 }}>
          <SkeletonDot size={8} />
          <SkeletonBar width={36} height={8} rounded={3} />
        </View>
      </View>
      <View
        style={{
          height,
          width: "100%",
          flexDirection: "row",
          alignItems: "flex-end",
          justifyContent: "space-between",
          paddingLeft: 28,
          paddingBottom: 24,
          position: "relative",
        }}
      >
        {bars.map((h, idx) => (
          <Skeleton
            key={idx}
            variant="rounded"
            startColor={SKELETON_START_COLOR}
            style={{
              width: `${100 / bars.length - 0.6}%`,
              height: Math.max(4, h * (height - 40)),
              borderRadius: 3,
            }}
          />
        ))}
      </View>
    </View>
  );
}

/** Lane row skeleton matching `LaneMetricsPanel`. */
function LaneHealthSkeleton({ count = 2 }: { count?: number }) {
  return (
    <View style={{ width: "100%" }}>
      {Array.from({ length: count }).map((_, idx) => (
        <View
          key={idx}
          className="rounded-xl border border-outline-200 bg-background-0"
          style={{
            marginBottom: 8,
            paddingHorizontal: 14,
            paddingVertical: 12,
          }}
        >
          {/* Header line: state dot + lane name + state pill + vllm pill (right) */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              columnGap: 8,
            }}
          >
            <SkeletonDot size={10} />
            <SkeletonBar width={220} height={12} />
            <SkeletonBar width={56} height={12} rounded={3} />
            <View style={{ marginLeft: "auto" }}>
              <SkeletonBar width={42} height={14} rounded={4} />
            </View>
          </View>
          {/* Model line */}
          <View style={{ marginTop: 8 }}>
            <SkeletonBar width={260} height={10} rounded={3} />
          </View>
          {/* KV cache row */}
          <View
            style={{
              marginTop: 12,
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <SkeletonBar width={56} height={9} rounded={3} />
            <SkeletonBar width={36} height={9} rounded={3} />
          </View>
          <View
            style={{
              marginTop: 6,
              height: 6,
              borderRadius: 999,
              backgroundColor: "rgba(15,23,42,0.06)",
            }}
          />
          {/* Stats row */}
          <View
            style={{
              marginTop: 10,
              flexDirection: "row",
              columnGap: 16,
            }}
          >
            <SkeletonBar width={68} height={9} rounded={3} />
            <SkeletonBar width={60} height={9} rounded={3} />
            <SkeletonBar width={64} height={9} rounded={3} />
          </View>
        </View>
      ))}
    </View>
  );
}

/** Status panel skeleton — 4 rows of dot+label / count / progress bar. */
function StatusPanelSkeleton() {
  return (
    <View style={{ rowGap: 14, width: "100%" }}>
      {Array.from({ length: 4 }).map((_, idx) => (
        <View key={idx} style={{ rowGap: 6 }}>
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <View
              style={{ flexDirection: "row", alignItems: "center", columnGap: 8 }}
            >
              <SkeletonDot size={8} />
              <SkeletonBar width={68 - idx * 4} height={10} rounded={3} />
            </View>
            <SkeletonBar width={84} height={10} rounded={3} />
          </View>
          <View
            style={{
              height: 6,
              borderRadius: 999,
              backgroundColor: "rgba(15,23,42,0.06)",
              overflow: "hidden",
            }}
          >
            <Skeleton
              variant="rounded"
              startColor={SKELETON_START_COLOR}
              style={{
                height: 6,
                width: `${[80, 30, 12, 8][idx]}%`,
                borderRadius: 999,
              }}
            />
          </View>
        </View>
      ))}
    </View>
  );
}

/** Workers & GPUs panel skeleton. */
function WorkerGpuSkeleton({ gpus = 2 }: { gpus?: number }) {
  return (
    <View style={{ width: "100%" }}>
      {/* Lane summary badge */}
      <View style={{ marginBottom: 12 }}>
        <SkeletonBar width={210} height={14} rounded={4} />
      </View>
      {Array.from({ length: gpus }).map((_, idx) => (
        <View
          key={idx}
          className="rounded-xl border border-outline-200 bg-background-0"
          style={{
            marginBottom: 8,
            paddingHorizontal: 14,
            paddingVertical: 12,
          }}
        >
          {/* Header: name + temp/power chips */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 10,
            }}
          >
            <View
              style={{ flexDirection: "row", alignItems: "center", columnGap: 8 }}
            >
              <SkeletonBar width={36} height={10} rounded={3} />
              <SkeletonBar width={120} height={12} />
            </View>
            <View
              style={{ flexDirection: "row", alignItems: "center", columnGap: 6 }}
            >
              <SkeletonBar width={42} height={16} rounded={4} />
              <SkeletonBar width={36} height={16} rounded={4} />
            </View>
          </View>
          {/* Memory row */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 4,
            }}
          >
            <SkeletonBar width={56} height={9} rounded={3} />
            <SkeletonBar width={120} height={9} rounded={3} />
          </View>
          <View
            style={{
              height: 6,
              borderRadius: 999,
              backgroundColor: "rgba(15,23,42,0.06)",
              overflow: "hidden",
              marginBottom: 12,
            }}
          >
            <Skeleton
              variant="rounded"
              startColor={SKELETON_START_COLOR}
              style={{ height: 6, width: idx === 0 ? "10%" : "9%", borderRadius: 999 }}
            />
          </View>
          {/* Utilization row */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 4,
            }}
          >
            <SkeletonBar width={64} height={9} rounded={3} />
            <SkeletonBar width={36} height={9} rounded={3} />
          </View>
          <View
            style={{
              height: 6,
              borderRadius: 999,
              backgroundColor: "rgba(15,23,42,0.06)",
              overflow: "hidden",
            }}
          >
            <Skeleton
              variant="rounded"
              startColor={SKELETON_START_COLOR}
              style={{ height: 6, width: "4%", borderRadius: 999 }}
            />
          </View>
        </View>
      ))}
    </View>
  );
}

/** VRAM remaining area-chart skeleton. */
function VramAreaChartSkeleton() {
  // y points trace a "smooth" curve so the placeholder feels like the real chart.
  const yPct = [0.92, 0.90, 0.88, 0.78, 0.55, 0.40, 0.65, 0.85, 0.91, 0.93, 0.93, 0.92];
  const height = 280;
  return (
    <View style={{ width: "100%" }}>
      {/* Live / Full History toggle + last sample badge */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          columnGap: 12,
          marginBottom: 12,
        }}
      >
        <SkeletonBar width={170} height={28} rounded={999} />
        <SkeletonBar width={170} height={10} rounded={3} />
      </View>
      <View
        style={{
          height,
          width: "100%",
          flexDirection: "row",
          alignItems: "flex-end",
          justifyContent: "space-between",
          paddingLeft: 28,
          paddingRight: 4,
          paddingBottom: 24,
        }}
      >
        {yPct.map((p, idx) => (
          <Skeleton
            key={idx}
            variant="rounded"
            startColor={SKELETON_START_COLOR}
            style={{
              width: `${100 / yPct.length - 0.6}%`,
              height: Math.max(8, p * (height - 40)),
              borderRadius: 4,
            }}
          />
        ))}
      </View>
      {/* Range slider placeholder */}
      <View style={{ marginTop: 10 }}>
        <SkeletonBar width="100%" height={28} rounded={6} />
      </View>
    </View>
  );
}

/* ── KPI helpers ────────────────────────────────────────────── */

function Sparkline({
  data,
  color,
  width = 92,
  height = 28,
}: {
  data: number[];
  color: string;
  width?: number;
  height?: number;
}) {
  // Render nothing for empty / all-zero series so we don't paint a flat baseline.
  const max = Math.max(...data, 0);
  if (!data.length || max <= 0) return null;
  const points = data
    .map((v, i) => {
      const x = data.length === 1 ? width / 2 : (i / (data.length - 1)) * width;
      const y = height - (v / max) * (height - 2) - 1;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  return (
    <Svg width={width} height={height} style={{ overflow: "visible" } as any}>
      <Polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

type KpiCardProps = {
  label: string;
  accent?: string;
  value: string;
  hint?: React.ReactNode;
  spark?: number[];
  sparkColor?: string;
  rightSlot?: React.ReactNode;
};

function KpiCard({ label, accent, value, hint, spark, sparkColor, rightSlot }: KpiCardProps) {
  return (
    <View
      className="rounded-2xl border border-outline-200 bg-background-0 shadow-soft-1"
      style={{
        // Layout: each card claims ~25% width. flex-grow:0 prevents a tall
        // sibling from inflating others, flex-shrink:1 lets cards yield to
        // gaps. alignSelf stretch so every card in a row matches the tallest
        // (equal heights even when one card has a 2-line hint).
        flexBasis: "calc(25% - 9px)" as any,
        flexGrow: 0,
        flexShrink: 1,
        minWidth: 200,
        alignSelf: "stretch",
        // Visual chrome
        paddingTop: 14,
        paddingBottom: 14,
        paddingLeft: 18,
        paddingRight: 18,
        // Block-level layout for predictability — RN-Web View defaults to
        // display:flex column which is fine, but the explicit declaration
        // here defends against accidental inheritance.
        display: "flex",
        flexDirection: "column",
        justifyContent: "flex-start",
      }}
    >
      {/* Row 1: dot + label */}
      <View
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          columnGap: 8,
        }}
      >
        <View
          style={{
            height: 6,
            width: 6,
            borderRadius: 99,
            backgroundColor: accent || "#94A3B8",
          }}
        />
        <Text
          className="text-typography-500"
          style={{
            fontSize: 11,
            fontWeight: "500",
            letterSpacing: 0.6,
            textTransform: "uppercase",
          }}
        >
          {label}
        </Text>
      </View>
      {/* Row 2: big number + sparkline / right slot */}
      <View
        style={{
          marginTop: 6,
          display: "flex",
          flexDirection: "row",
          alignItems: "flex-end",
          justifyContent: "space-between",
          columnGap: 12,
        }}
      >
        <Text
          className="text-typography-900"
          style={{ fontSize: 26, fontWeight: "600" }}
          numberOfLines={1}
        >
          {value}
        </Text>
        {rightSlot ? (
          rightSlot
        ) : spark && spark.length > 0 ? (
          <Sparkline data={spark} color={sparkColor || "#1E3A8A"} />
        ) : null}
      </View>
      {/* Row 3: hint */}
      {hint ? (
        <View style={{ marginTop: 6 }}>
          {typeof hint === "string" ? (
            <Text className="text-xs text-typography-500">{hint}</Text>
          ) : (
            hint
          )}
        </View>
      ) : null}
    </View>
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
  const [stats, setStats] = useState<RequestLogStats | null>(null);
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
  const [vramProviderMetaByName, setVramProviderMetaByName] = useState<{
    [name: string]: VramProviderMeta;
  }>({});
  const [selectedVramProvider, setSelectedVramProvider] = useState<
    string | null
  >(null);
  const [vramBaseline, setVramBaseline] = useState<any[]>([]);
  const [vramBucketSizeSec, setVramBucketSizeSec] = useState(10);
  const [vramTotalBuckets, setVramTotalBuckets] = useState(8640);
  const vramSignatureRef = useRef<string | null>(null);
  const currentVramUtcDayRef = useRef<string | null>(null);

  // Lane + device state derived from VRAM data
  const [devicesByProvider, setDevicesByProvider] = useState<
    Record<string, DeviceInfo[]>
  >({});

  const vramProviders = useMemo(() => {
    const source = usePlotlyWeb ? vramRawDataByProvider : vramDataByProvider;
    return Object.keys(source).sort();
  }, [usePlotlyWeb, vramDataByProvider, vramRawDataByProvider]);



  useEffect(() => {
    if (!vramProviders.length) {
      setSelectedVramProvider(null);
      return;
    }
    const source = usePlotlyWeb ? vramRawDataByProvider : vramDataByProvider;
    const rankedProviders = [...vramProviders].sort((left, right) => {
      const leftMeta = vramProviderMetaByName[left];
      const rightMeta = vramProviderMetaByName[right];
      const leftConnected =
        leftMeta?.connection_state !== "offline" && leftMeta?.connected !== false;
      const rightConnected =
        rightMeta?.connection_state !== "offline" && rightMeta?.connected !== false;
      const leftHasSamples = (source[left] || []).length > 0;
      const rightHasSamples = (source[right] || []).length > 0;
      const leftScore = (leftHasSamples ? 2 : 0) + (leftConnected ? 1 : 0);
      const rightScore = (rightHasSamples ? 2 : 0) + (rightConnected ? 1 : 0);
      if (leftScore !== rightScore) return rightScore - leftScore;
      return left.localeCompare(right);
    });

    if (
      !selectedVramProvider ||
      !vramProviders.includes(selectedVramProvider)
    ) {
      setSelectedVramProvider(rankedProviders[0]);
    }
  }, [
    selectedVramProvider,
    usePlotlyWeb,
    vramDataByProvider,
    vramProviderMetaByName,
    vramProviders,
    vramRawDataByProvider,
  ]);

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
  const selectedVramProviderMeta = selectedVramProvider
    ? vramProviderMetaByName[selectedVramProvider] || null
    : null;

  // Derive per-provider lane data from the latest raw VRAM sample
  const lanesByProvider = useMemo<Record<string, Record<string, LaneSignalData>>>(() => {
    const result: Record<string, Record<string, LaneSignalData>> = {};
    for (const [providerName, samples] of Object.entries(vramRawDataByProvider)) {
      if (!samples.length) continue;
      const latest = samples[samples.length - 1] as VramV2Sample | undefined;
      const lanes = latest?.scheduler_signals?.lanes;
      if (lanes && typeof lanes === "object") {
        result[providerName] = lanes;
      }
    }
    return result;
  }, [vramRawDataByProvider]);

  // Latest sample per provider (for WorkerGpuPanel)
  const latestSampleByProvider = useMemo<Record<string, VramV2Sample | null>>(() => {
    const result: Record<string, VramV2Sample | null> = {};
    for (const [providerName, samples] of Object.entries(vramRawDataByProvider)) {
      result[providerName] = samples.length
        ? (samples[samples.length - 1] as VramV2Sample)
        : null;
    }
    return result;
  }, [vramRawDataByProvider]);

  // Lane state breakdown across all providers. "Active" = lane is loaded
  // into VRAM (or actively serving / spinning up). Sleeping/cold/stopped
  // lanes are not active. The KPI also surfaces sleeping/cold counts in
  // the hint so users can see the full state distribution.
  const laneStateCounts = useMemo(() => {
    const out = {
      loaded: 0,
      running: 0,
      starting: 0,
      sleeping: 0,
      cold: 0,
      stopped: 0,
      error: 0,
      activeRequests: 0,
      total: 0,
    };
    for (const lanes of Object.values(lanesByProvider)) {
      for (const lane of Object.values(lanes)) {
        out.total += 1;
        out.activeRequests += lane.active_requests || 0;
        switch (lane.runtime_state) {
          case "loaded":   out.loaded   += 1; break;
          case "running":  out.running  += 1; break;
          case "starting": out.starting += 1; break;
          case "sleeping": out.sleeping += 1; break;
          case "cold":     out.cold     += 1; break;
          case "stopped":  out.stopped  += 1; break;
          case "error":    out.error    += 1; break;
        }
      }
    }
    return out;
  }, [lanesByProvider]);

  const derivedActiveLanes =
    laneStateCounts.loaded + laneStateCounts.running + laneStateCounts.starting;

  // All-provider VRAM for the global "Active lanes" KPI: sum the nvidia-smi figures
  // (scheduler_signals.provider) across providers, matching the all-provider lane count.
  const allProviderVramSummary = useMemo(() => {
    let totalMb = 0;
    let usedMb = 0;
    let freeMb = 0;
    for (const sample of Object.values(latestSampleByProvider)) {
      const vram = extractProviderVramMb(sample);
      totalMb += vram.totalMb;
      freeMb += vram.freeMb;
      usedMb += vram.usedMb;
    }
    return {
      usedGb: toDecimalGb(usedMb * BYTES_PER_MIB),
      freeGb: toDecimalGb(freeMb * BYTES_PER_MIB),
      totalGb: toDecimalGb(totalMb * BYTES_PER_MIB),
    };
  }, [latestSampleByProvider]);

  // Selected provider lane data for the pie chart
  const selectedProviderLanes = useMemo<Record<string, LaneSignalData>>(() => {
    if (!selectedVramProvider) return {};
    return lanesByProvider[selectedVramProvider] ?? {};
  }, [lanesByProvider, selectedVramProvider]);

  const selectedProviderTotalVramMb = useMemo(() => {
    if (!selectedVramProvider) return 0;
    return extractProviderVramMb(latestSampleByProvider[selectedVramProvider]).totalMb;
  }, [latestSampleByProvider, selectedVramProvider]);

  const selectedProviderFreeVramMb = useMemo(() => {
    if (!selectedVramProvider) return 0;
    return extractProviderVramMb(latestSampleByProvider[selectedVramProvider]).freeMb;
  }, [latestSampleByProvider, selectedVramProvider]);

  const vramPieData = useMemo(() => {
    const usedGb = latestVramSample?.used_vram_gb ?? 0;
    const remainingGb = latestVramSample?.remaining_vram_gb ?? 0;
    const totalGb = latestVramSample?.total_vram_gb ?? usedGb + remainingGb;
    if (totalGb <= 0) return [];

    const reportedModels = latestVramSample?.loaded_models ?? [];
    const rawModelSlices = reportedModels
      .map((model, index) => ({
        value: Number(model.size_gb || 0),
        color: MODEL_SLICE_COLORS[index % MODEL_SLICE_COLORS.length],
        text: model.name,
      }))
      .filter((slice) => slice.value > 0);

    const attributedUsedGb = rawModelSlices.reduce(
      (sum, slice) => sum + slice.value,
      0
    );
    const modelScale =
      attributedUsedGb > usedGb && attributedUsedGb > 0
        ? usedGb / attributedUsedGb
        : 1;
    const modelSlices = rawModelSlices.map((slice) => ({
      ...slice,
      value: Number((slice.value * modelScale).toFixed(3)),
    }));
    const modeledUsedGb = modelSlices.reduce((sum, slice) => sum + slice.value, 0);
    const otherUsedGb = Math.max(usedGb - modeledUsedGb, 0);

    return [
      ...modelSlices,
      {
        value: otherUsedGb,
        color: OTHER_SLICE_COLOR,
        text:
          modelSlices.length > 0
            ? "Other used"
            : "Used",
      },
      {
        value: remainingGb,
        color: FREE_SLICE_COLOR,
        text: "Free",
      },
    ].filter((slice) => slice.value > 0);
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
      providers: VramProviderPayload[],
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
      providers: VramProviderPayload[]
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
    ): RequestLogStats["timeSeries"] => {
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

      const rawSeries: RequestLogStats["timeSeries"] = [];
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

  // Cap the rolling buffer of raw VRAM samples we keep in memory. The
  // chart's live window is ~30 minutes; the worker heartbeat is ~5s, so
  // 720 samples covers ~1 hour and is plenty for any visible range.
  // Without this cap, the buffer grows unbounded across a session and the
  // O(N) merge / sort / re-derive on every delta becomes the dominant
  // source of stutter on the page.
  const RAW_VRAM_SAMPLE_CAP = 720;

  const replaceRawVramSeries = useCallback(
    (
      providers: VramProviderPayload[]
    ) => {
      const next: { [url: string]: any[] } = {};
      const nextMeta: { [name: string]: VramProviderMeta } = {};
      const nextDevices: Record<string, DeviceInfo[]> = {};
      for (const provider of providers || []) {
        const sortedSamples = (provider.data || [])
          .filter((sample) => sample?.timestamp)
          .sort(
            (a, b) =>
              new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
          );
        const samples =
          sortedSamples.length > RAW_VRAM_SAMPLE_CAP
            ? sortedSamples.slice(sortedSamples.length - RAW_VRAM_SAMPLE_CAP)
            : sortedSamples;
        next[provider.name] = samples;
        nextMeta[provider.name] = {
          provider_id: provider.provider_id,
          connected: provider.connected,
          connection_state: provider.connection_state,
          provider_type: provider.provider_type,
          runtime_modes: provider.runtime_modes,
          transport_connected: provider.transport_connected,
          last_heartbeat: provider.last_heartbeat,
        };
        // Extract top-level devices from provider payload
        if (Array.isArray((provider as any).devices) && (provider as any).devices.length) {
          nextDevices[provider.name] = (provider as any).devices;
        }
      }
      setVramRawDataByProvider(next);
      setVramProviderMetaByName(nextMeta);
      setDevicesByProvider(nextDevices);
    },
    []
  );

  const appendRawVramSeries = useCallback(
    (
      providers: VramProviderPayload[]
    ) => {
      if (!providers || providers.length === 0) return;
      setVramProviderMetaByName((prevMeta) => {
        let nextMeta = prevMeta;
        for (const provider of providers) {
          const meta: VramProviderMeta = {
            provider_id: provider.provider_id,
            connected: provider.connected,
            connection_state: provider.connection_state,
            provider_type: provider.provider_type,
            runtime_modes: provider.runtime_modes,
            transport_connected: provider.transport_connected,
            last_heartbeat: provider.last_heartbeat,
          };
          const current = prevMeta[provider.name];
          const same =
            current?.provider_id === meta.provider_id &&
            current?.connected === meta.connected &&
            current?.connection_state === meta.connection_state &&
            current?.provider_type === meta.provider_type &&
            JSON.stringify(current?.runtime_modes || []) ===
              JSON.stringify(meta.runtime_modes || []) &&
            current?.transport_connected === meta.transport_connected &&
            current?.last_heartbeat === meta.last_heartbeat;
          if (same) continue;
          if (nextMeta === prevMeta) nextMeta = { ...prevMeta };
          nextMeta[provider.name] = meta;
        }
        return nextMeta;
      });
      // Update devices from top-level provider payload
      setDevicesByProvider((prev) => {
        let next = prev;
        for (const provider of providers) {
          if (Array.isArray((provider as any).devices) && (provider as any).devices.length) {
            if (next === prev) next = { ...prev };
            next[provider.name] = (provider as any).devices;
          }
        }
        return next;
      });
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
          const capped =
            merged.length > RAW_VRAM_SAMPLE_CAP
              ? merged.slice(merged.length - RAW_VRAM_SAMPLE_CAP)
              : merged;
          if (next === prev) next = { ...prev };
          next[provider.name] = capped;
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

  // Pre-warm the Plotly CDN download as soon as the page mounts. Each
  // chart component lazily calls loadPlotly() on first render, but those
  // effects only fire after data arrives and the charts render. Kicking
  // it off here lets the ~1.5 MB script download race with the websocket
  // init dance instead of stacking on top of it.
  useEffect(() => {
    if (Platform.OS !== "web") return;
    void import("@/components/statistics/plotly-loader.web").then((mod) =>
      mod.loadPlotly().catch(() => {
        /* errors surface in the chart components */
      })
    );
  }, []);

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
    // Union the requested window with the actual data extent so loaded data is
    // never filtered out (avoids a transient empty chart after clearing zoom).
    const rangeStartMs = customRange
      ? customRange.start.getTime()
      : Math.min(
          timelineRangeRef.current?.startMs ?? fallbackStart,
          fallbackStart
        );
    const rangeEndMs = customRange
      ? customRange.end.getTime()
      : Math.max(
          timelineRangeRef.current?.endMs ?? fallbackEnd,
          fallbackEnd
        );

    if (
      !Number.isFinite(rangeStartMs) ||
      !Number.isFinite(rangeEndMs) ||
      rangeEndMs <= rangeStartMs
    ) {
      return { totalLineData: [], cloudLineData: [], localLineData: [] };
    }

    const bucketMs = chooseDynamicBucketMs(rangeEndMs - rangeStartMs);

    let series: RequestLogStats["timeSeries"] = [];

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

    // Group by modelId (not name) so distinct models sharing a display name aren't merged.
    const byModel: Record<string, Map<number, number>> = {};
    for (const entry of mts) {
      const key = String(entry.modelId);
      if (!byModel[key]) {
        byModel[key] = new Map();
      }
      // Aggregate into the nearest bucket that exists in our totalLineData
      // The backend bucket timestamps should align since we use the same bucket size
      const ts = entry.timestamp;
      if (bucketSet.has(ts)) {
        const m = byModel[key];
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
        const m = byModel[key];
        m.set(closest, (m.get(closest) || 0) + entry.count);
      }
    }

    // Build series with a point for every bucket (0 if no data)
    const result: Record<
      string,
      Array<{ value: number; timestamp: number }>
    > = {};
    for (const [modelId, bucketMap] of Object.entries(byModel)) {
      result[modelId] = bucketTimestamps.map((ts) => ({
        value: bucketMap.get(ts) || 0,
        timestamp: ts,
      }));
    }
    return result;
  }, [stats?.modelTimeSeries, totalLineData]);

  // modelId -> label: plain name, suffixed with the id only when the name collides across ids.
  const modelLabelById = useMemo<Record<string, string>>(() => {
    const nameById: Record<string, string> = {};
    for (const m of stats?.modelBreakdown ?? []) {
      nameById[String(m.modelId)] = m.modelName;
    }
    for (const e of stats?.modelTimeSeries ?? []) {
      const key = String(e.modelId);
      if (!(key in nameById)) nameById[key] = e.modelName;
    }
    const nameCount: Record<string, number> = {};
    for (const name of Object.values(nameById)) {
      nameCount[name] = (nameCount[name] || 0) + 1;
    }
    const labels: Record<string, string> = {};
    for (const [id, name] of Object.entries(nameById)) {
      labels[id] = (nameCount[name] || 0) > 1 ? `${name} (${id})` : name;
    }
    return labels;
  }, [stats?.modelBreakdown, stats?.modelTimeSeries]);

  /** Model colors keyed by model_id, shared between bar and pie charts */
  const modelColors = useMemo<Record<string, string>>(() => {
    // Assign by modelBreakdown order (most requests first) for consistency
    const breakdown = stats?.modelBreakdown ?? [];
    const map: Record<string, string> = {};
    breakdown.forEach((m, idx) => {
      map[String(m.modelId)] = MODEL_PALETTE[idx % MODEL_PALETTE.length];
    });
    // Also cover any model_ids from modelSeriesMap not in breakdown
    Object.keys(modelSeriesMap).forEach((id) => {
      if (!map[id]) {
        map[id] =
          MODEL_PALETTE[Object.keys(map).length % MODEL_PALETTE.length];
      }
    });
    return map;
  }, [modelSeriesMap, stats?.modelBreakdown]);

  // Derived from the same windowed series as the volume chart so they stay in
  // sync with it (previously used full-period stats and updated unreliably).
  const providerPieData = useMemo(() => {
    const cloudSum = cloudLineData.reduce((acc, p) => acc + (p.value || 0), 0);
    const localSum = localLineData.reduce((acc, p) => acc + (p.value || 0), 0);
    return [
      { value: cloudSum, color: CHART_PALETTE.cloud, text: "Cloud" },
      { value: localSum, color: CHART_PALETTE.local, text: "Local" },
    ].filter((d) => d.value > 0);
  }, [cloudLineData, localLineData]);

  const modelPieData = useMemo(() => {
    // Top 5 models by volume over the visible buckets (keyed by model_id).
    const windowed = Object.entries(modelSeriesMap)
      .map(([id, series]) => ({
        id,
        total: series.reduce((acc, p) => acc + (p.value || 0), 0),
      }))
      .filter((m) => m.total > 0)
      .sort((a, b) => b.total - a.total);

    // Fallback to the full-period breakdown if no windowed series yet.
    if (windowed.length === 0) {
      return (stats?.modelBreakdown ?? []).slice(0, 5).map((m) => ({
        value: m.requestCount,
        color: modelColors[String(m.modelId)] || "#94A3B8",
        text: modelLabelById[String(m.modelId)] || m.modelName,
      }));
    }

    return windowed.slice(0, 5).map((m) => ({
      value: m.total,
      color: modelColors[m.id] || "#94A3B8",
      text: modelLabelById[m.id] || m.id,
    }));
  }, [modelSeriesMap, modelColors, modelLabelById, stats?.modelBreakdown]);

  // Per-section readiness flags — each card flips from skeleton to
  // real content as soon as its own data resolves. The page no longer
  // waits for everything to load before rendering anything.
  const statsReady = stats != null;
  const vramReady = useMemo(
    () => Object.values(vramRawDataByProvider).some((arr) => arr && arr.length > 0),
    [vramRawDataByProvider]
  );
  const showFatalError = error != null && !statsReady;

  // Derived KPI values (data unchanged, just presentation)
  const totalRequests = stats?.totals.requests ?? 0;
  const cloudRequests = stats?.totals.cloudRequests ?? 0;
  const localRequests = stats?.totals.localRequests ?? 0;
  const cloudPct =
    totalRequests > 0 ? Math.round((cloudRequests / totalRequests) * 100) : 0;
  const coldStarts = stats?.totals.coldStarts ?? 0;
  const warmStarts = stats?.totals.warmStarts ?? 0;
  const coldDenominator = coldStarts + warmStarts;
  const coldPct =
    coldDenominator > 0 ? Math.round((coldStarts / coldDenominator) * 100) : 0;

  const sparkTotal = (stats?.timeSeries ?? [])
    .slice(-30)
    .map((p) => p.total || 0);
  const sparkCloud = (stats?.timeSeries ?? [])
    .slice(-30)
    .map((p) => p.cloud || 0);
  const sparkLocal = (stats?.timeSeries ?? [])
    .slice(-30)
    .map((p) => p.local || 0);

  // Active vs total lane counts across all providers
  let totalLanesAcrossProviders = 0;
  for (const lanes of Object.values(lanesByProvider)) {
    totalLanesAcrossProviders += Object.keys(lanes).length;
  }

  // Per-lane mini-bars for the active-lanes KPI
  const allLanesForKpi = Object.values(lanesByProvider).flatMap((p) =>
    Object.values(p)
  );
  const maxLaneVramMb = allLanesForKpi.reduce(
    (m, l) => Math.max(m, l.effective_vram_mb || 0),
    0
  );

  // Status bars data (uses existing stats.statusCounts)
  type StatusRow = { label: string; key: string; value: number; color: string };
  const statusEntries: StatusRow[] = [
    { label: "Success", key: "success", value: stats?.statusCounts?.success ?? 0, color: "#10B981" },
    { label: "Error", key: "error", value: stats?.statusCounts?.error ?? 0, color: "#EF4444" },
    { label: "Timeout", key: "timeout", value: stats?.statusCounts?.timeout ?? 0, color: "#F59E0B" },
    { label: "Pending", key: "pending", value: stats?.statusCounts?.pending ?? 0, color: "#8B5CF6" },
  ];
  const statusTotalCount = statusEntries.reduce((s, x) => s + x.value, 0);

  // Refresh icon spin animation
  const refreshSpin = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (refreshing) {
      const loop = Animated.loop(
        Animated.timing(refreshSpin, {
          toValue: 1,
          duration: 900,
          easing: Easing.linear,
          useNativeDriver: true,
        })
      );
      loop.start();
      return () => loop.stop();
    }
    refreshSpin.setValue(0);
  }, [refreshing, refreshSpin]);
  const refreshSpinDeg = refreshSpin.interpolate({
    inputRange: [0, 1],
    outputRange: ["0deg", "360deg"],
  });

  return (
    <View className="w-full">
      <VStack className="w-full" style={{ rowGap: 20 }}>
        {/* Page header */}
        <HStack
          className="flex-wrap items-center justify-between"
          style={{ columnGap: 16, rowGap: 8 }}
        >
          <View style={{ minWidth: 0, flexShrink: 1 }}>
            <Text
              className="text-typography-900"
              style={{ fontSize: 26, fontWeight: "600", letterSpacing: -0.3 }}
            >
              Statistics
            </Text>
            <Text className="text-typography-500" style={{ fontSize: 13.5, marginTop: 2 }}>
              Real-time request volume, VRAM, and lane health across all providers.
            </Text>
          </View>
          <Pressable
            onPress={onRefresh}
            disabled={refreshing}
            className="rounded-full border border-outline-200 bg-background-0 web:cursor-pointer web:hover:border-outline-300"
            style={{
              paddingHorizontal: 14,
              height: 34,
              flexDirection: "row",
              alignItems: "center",
              columnGap: 8,
              opacity: refreshing ? 0.7 : 1,
            }}
            accessibilityLabel="Refresh statistics"
          >
            <Animated.View style={{ transform: [{ rotate: refreshSpinDeg }] }}>
              <RotateCw size={14} color="#737373" />
            </Animated.View>
            <Text className="text-typography-900" style={{ fontSize: 12 }}>
              {refreshing ? "Refreshing…" : "Refresh"}
            </Text>
          </Pressable>
        </HStack>

        {showFatalError ? (
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
        ) : (
          <VStack className="w-full" space="lg">
            {/* KPI strip */}
            <View
              style={{
                width: "100%",
                display: "flex",
                flexDirection: "row",
                flexWrap: "wrap",
                alignItems: "stretch",
                alignContent: "flex-start",
                columnGap: 12,
                rowGap: 12,
              }}
            >
              {statsReady ? (
                <KpiCard
                  label={`Requests · ${timeWindow}`}
                  accent="#94A3B8"
                  value={totalRequests.toLocaleString()}
                  spark={sparkTotal}
                  sparkColor={CHART_PALETTE.total}
                  hint={
                    <Text className="text-typography-500" style={{ fontSize: 12 }}>
                      avg run{" "}
                      <Text className="text-typography-900">
                        {(stats?.totals.avgRunSeconds ?? 0).toFixed(2)}s
                      </Text>
                      {" · queue "}
                      <Text className="text-typography-900">
                        {(stats?.totals.avgQueueSeconds ?? 0).toFixed(2)}s
                      </Text>
                    </Text>
                  }
                />
              ) : (
                <KpiCardSkeleton />
              )}
              {statsReady ? (
                <KpiCard
                  label="Cloud share"
                  accent={CHART_PALETTE.cloud}
                  value={`${cloudPct}%`}
                  spark={sparkCloud}
                  sparkColor={CHART_PALETTE.cloud}
                  hint={
                    <Text className="text-typography-500" style={{ fontSize: 12 }}>
                      <Text className="text-typography-900">
                        {cloudRequests.toLocaleString()}
                      </Text>{" "}
                      cloud ·{" "}
                      <Text className="text-typography-900">
                        {localRequests.toLocaleString()}
                      </Text>{" "}
                      local
                    </Text>
                  }
                />
              ) : (
                <KpiCardSkeleton />
              )}
              {statsReady ? (
                <KpiCard
                  label="Cold starts"
                  accent={CHART_PALETTE.local}
                  value={`${coldPct}%`}
                  spark={sparkLocal}
                  sparkColor={CHART_PALETTE.local}
                  hint={
                    <Text className="text-typography-500" style={{ fontSize: 12 }}>
                      <Text className="text-typography-900">{coldStarts}</Text>
                      {" of "}
                      <Text className="text-typography-900">
                        {coldDenominator.toLocaleString()}
                      </Text>{" "}
                      local starts
                    </Text>
                  }
                />
              ) : (
                <KpiCardSkeleton />
              )}
              {vramReady ? (
                <KpiCard
                  label="Active lanes"
                  accent={getLaneStateColor("loaded")}
                value={`${derivedActiveLanes} / ${totalLanesAcrossProviders}`}
                hint={
                  totalLanesAcrossProviders > 0 ? (
                    <View style={{ flexDirection: "column", rowGap: 2 }}>
                      <View
                        style={{
                          flexDirection: "row",
                          flexWrap: "wrap",
                          columnGap: 8,
                          rowGap: 2,
                        }}
                      >
                        {(laneStateCounts.loaded + laneStateCounts.running) > 0 && (
                          <Text style={{ fontSize: 12 }}>
                            <Text
                              style={{
                                color: getLaneStateColor("loaded"),
                                fontWeight: "600",
                              }}
                            >
                              {laneStateCounts.loaded + laneStateCounts.running}
                            </Text>
                            <Text className="text-typography-500"> loaded</Text>
                          </Text>
                        )}
                        {laneStateCounts.starting > 0 && (
                          <Text style={{ fontSize: 12 }}>
                            <Text
                              style={{
                                color: getLaneStateColor("starting"),
                                fontWeight: "600",
                              }}
                            >
                              {laneStateCounts.starting}
                            </Text>
                            <Text className="text-typography-500"> starting</Text>
                          </Text>
                        )}
                        {laneStateCounts.sleeping > 0 && (
                          <Text style={{ fontSize: 12 }}>
                            <Text
                              style={{
                                color: getLaneStateColor("sleeping"),
                                fontWeight: "600",
                              }}
                            >
                              {laneStateCounts.sleeping}
                            </Text>
                            <Text className="text-typography-500"> sleeping</Text>
                          </Text>
                        )}
                        {laneStateCounts.cold > 0 && (
                          <Text style={{ fontSize: 12 }}>
                            <Text
                              style={{
                                color: getLaneStateColor("cold"),
                                fontWeight: "600",
                              }}
                            >
                              {laneStateCounts.cold}
                            </Text>
                            <Text className="text-typography-500"> cold</Text>
                          </Text>
                        )}
                        {(laneStateCounts.stopped + laneStateCounts.error) > 0 && (
                          <Text style={{ fontSize: 12 }}>
                            <Text
                              style={{ color: "#EF4444", fontWeight: "600" }}
                            >
                              {laneStateCounts.stopped + laneStateCounts.error}
                            </Text>
                            <Text className="text-typography-500"> stopped</Text>
                          </Text>
                        )}
                      </View>
                      {allProviderVramSummary.totalGb > 0 && (
                        <Text
                          className="text-typography-500"
                          style={{ fontSize: 12 }}
                        >
                          <Text className="text-typography-900">
                            {allProviderVramSummary.usedGb.toFixed(1)}
                          </Text>
                          {" / "}
                          <Text className="text-typography-900">
                            {allProviderVramSummary.totalGb.toFixed(0)} GB
                          </Text>{" "}
                          VRAM
                        </Text>
                      )}
                    </View>
                  ) : null
                }
                rightSlot={
                  allLanesForKpi.length > 0 ? (
                    <View
                      style={{
                        flexDirection: "row",
                        alignItems: "flex-end",
                        height: 28,
                        columnGap: 2,
                      }}
                    >
                      {allLanesForKpi.slice(0, 12).map((lane, i) => {
                        const ratio =
                          maxLaneVramMb > 0
                            ? (lane.effective_vram_mb || 0) / maxLaneVramMb
                            : 0;
                        const h = Math.max(4, Math.round(ratio * 28));
                        const c = getLaneStateColor(lane.runtime_state);
                        return (
                          <View
                            key={i}
                            style={{
                              width: 6,
                              height: h,
                              borderRadius: 2,
                              backgroundColor: c,
                            }}
                          />
                        );
                      })}
                    </View>
                  ) : undefined
                }
              />
              ) : (
                <KpiCardSkeleton />
              )}
            </View>

            {/* Provider-scoped row: VRAM utilization + Lane health + Workers & GPUs, all
                driven by the shared selector below. Selector hides when only one provider exists. */}
            <View className="rounded-2xl border border-outline-200 bg-background-50 p-3" style={{ rowGap: 12 }}>
              {/* Shared selector header */}
              <HStack className="items-center gap-3" style={{ paddingHorizontal: 4 }}>
                <Text className="text-sm font-medium text-typography-700">Provider</Text>
                {vramProviders.length > 1 ? (
                  <View style={{ minWidth: 220 }}>
                    <Select
                      selectedValue={selectedVramProvider ?? ""}
                      onValueChange={(val) => setSelectedVramProvider(val || null)}
                    >
                      <SelectTrigger className="rounded-full border border-outline-200 bg-background-0 px-3 py-2">
                        <SelectInput
                          placeholder="Select provider"
                          value={selectedVramProvider ?? ""}
                          className="text-typography-900"
                        />
                      </SelectTrigger>
                      <SelectPortal>
                        <SelectBackdrop />
                        <SelectContent className="border border-outline-200 bg-background-0">
                          {vramProviders.map((p) => (
                            <SelectItem key={p} label={p} value={p} />
                          ))}
                        </SelectContent>
                      </SelectPortal>
                    </Select>
                  </View>
                ) : (
                  <Text className="text-sm text-typography-500">
                    {selectedVramProvider ?? "—"}
                  </Text>
                )}
              </HStack>

              <View className="w-full" style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "stretch", columnGap: 16, rowGap: 16 }}>
                <View className="w-full" style={{ flexGrow: 1, flexShrink: 1, flexBasis: 0, minWidth: 280 }}>
                  <ChartCard
                    title="VRAM utilization"
                    subtitle={
                      selectedVramProvider
                        ? `${selectedVramProvider}${
                            vramSummary.modelsLoaded
                              ? ` · ${vramSummary.modelsLoaded} model${vramSummary.modelsLoaded === 1 ? "" : "s"} loaded`
                              : ""
                          }`
                        : "Memory across local providers."
                    }
                  >
                  {(width) => {
                    if (!vramReady) {
                      return <DonutSkeleton diameter={200} legendItems={3} centerRows={3} />;
                    }
                    const hasLanes = Object.keys(selectedProviderLanes).length > 0;
                    if (usePlotlyWeb && hasLanes) {
                      return (
                        <LaneVramPie
                          width={width}
                          lanes={selectedProviderLanes}
                          totalVramMb={selectedProviderTotalVramMb}
                          freeVramMb={selectedProviderFreeVramMb}
                        />
                      );
                    }
                    if (!vramPieData.length) {
                      return (
                        <EmptyState
                          message={
                            selectedVramProviderMeta?.connection_state === "offline" ||
                            selectedVramProviderMeta?.connected === false
                              ? `${selectedVramProvider} is offline.`
                              : "No memory data yet."
                          }
                        />
                      );
                    }
                    if (usePlotlyWeb) {
                      return (
                        <PlotlyPieChart
                          data={vramPieData}
                          width={width}
                          height={260}
                          pieScale={0.9}
                          legendPosition="bottom"
                          hoverValueSuffix=" GB"
                          hoverValueDecimals={2}
                          centerText={{
                            top: "used",
                            middle: `${vramSummary.usedGb.toFixed(1)} GB`,
                            bottom: `of ${vramSummary.totalGb.toFixed(1)} GB`,
                          }}
                        />
                      );
                    }
                    const { radius, innerRadius } = getPieSizing(width, 0.85);
                    return (
                      <View style={{ alignItems: "center" }}>
                        <View style={{ alignItems: "center", justifyContent: "center" }}>
                          <View
                            pointerEvents="none"
                            className="absolute rounded-full bg-background-0"
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
                                <Text className="text-xs text-typography-500">used</Text>
                                <Text className="text-xl font-semibold text-typography-900">
                                  {vramSummary.usedGb.toFixed(1)} GB
                                </Text>
                                <Text className="text-xs text-typography-500">
                                  of {vramSummary.totalGb.toFixed(1)} GB
                                </Text>
                              </View>
                            )}
                          />
                        </View>
                        <VStack className="mt-3 space-y-1">
                          {vramPieData.map((d, i) => (
                            <HStack key={i} space="xs" className="items-center">
                              <View
                                style={{
                                  width: 8,
                                  height: 8,
                                  borderRadius: 4,
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
                  }}
                  </ChartCard>
                </View>
                <View className="w-full" style={{ flexGrow: 1, flexShrink: 1, flexBasis: 0, minWidth: 280 }}>
                  <ChartCard
                    title="Lane health"
                    subtitle="Per-lane runtime state, KV cache, and TTFT."
                    right={
                      vramReady && totalLanesAcrossProviders > 0 ? (
                        <Text className="text-typography-500" style={{ fontSize: 12 }}>
                          {totalLanesAcrossProviders} lane
                          {totalLanesAcrossProviders === 1 ? "" : "s"}
                        </Text>
                      ) : undefined
                    }
                  >
                    {() => !vramReady ? (
                      <LaneHealthSkeleton count={2} />
                    ) : (
                      <LaneMetricsPanel
                        lanesByProvider={lanesByProvider}
                        providerMeta={vramProviderMetaByName}
                        selectedProvider={selectedVramProvider}
                      />
                    )}
                  </ChartCard>
                </View>
                <View className="w-full" style={{ flexGrow: 1, flexShrink: 1, flexBasis: 0, minWidth: 280 }}>
                  <ChartCard
                    title="Workers & GPUs"
                    subtitle="Per-device hardware metrics from local providers."
                  >
                    {() => !vramReady ? (
                      <WorkerGpuSkeleton gpus={2} />
                    ) : (
                      <WorkerGpuPanel
                        providerLatestSamples={latestSampleByProvider}
                        providerDevices={devicesByProvider}
                        providerMeta={vramProviderMetaByName}
                        lanesByProvider={lanesByProvider}
                        activeProvider={selectedVramProvider}
                        apiKey={apiKey}
                      />
                    )}
                  </ChartCard>
                </View>
              </View>
            </View>

            {/* Recent requests (full width) */}
            <View className="w-full">
              <ChartCard
                title="Recent requests"
                subtitle="Latest activity from the request log."
              >
                {() => (
                  <PaginatedRequestList
                    liveRequests={latestRequests}
                    apiKey={apiKey}
                    nowMs={nowMs}
                  />
                )}
              </ChartCard>
            </View>

            {/* Range badge — appears when the user has zoomed the volume chart */}
            {showRangeBadge && (
              <Animated.View
                style={{
                  alignSelf: "center",
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
                <View className="flex-row items-center rounded-full border border-outline-200 bg-background-0 py-1 pl-4 pr-1">
                  <Text className="mr-3 text-sm font-medium text-typography-900">
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

            {/* Row 2: Request volume (col-8) + VRAM remaining (col-4) */}
            <View className="w-full" style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "stretch", columnGap: 16, rowGap: 16 }}>
              <View className="w-full" style={{ flexGrow: 8, flexShrink: 1, flexBasis: 0, minWidth: 360 }}>
                <ChartCard
                  title="Request volume"
                  subtitle="Per-bucket throughput across cloud and local providers."
                >
                  {(width) =>
                    !statsReady ? (
                      <BarChartSkeleton height={320} />
                    ) : !stats?.timeSeries?.length ? (
                      <EmptyState message="No request volume data in the selected range." />
                    ) : usePlotlyWeb ? (
                      <PlotlyRequestVolumeChart
                        width={width}
                        totalLineData={totalLineData}
                        cloudLineData={cloudLineData}
                        localLineData={localLineData}
                        modelSeriesMap={modelSeriesMap}
                        modelBreakdown={stats?.modelBreakdown}
                        modelColors={modelColors}
                        modelLabelById={modelLabelById}
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
                    )
                  }
                </ChartCard>
              </View>
              <View className="w-full" style={{ flexGrow: 4, flexShrink: 1, flexBasis: 0, minWidth: 280 }}>
                <ChartCard
                  title="VRAM remaining"
                  subtitle="Per-provider VRAM curve with per-lane breakdown."
                >
                  {(width) =>
                    !vramReady ? (
                      <VramAreaChartSkeleton />
                    ) : usePlotlyWeb ? (
                      <PlotlyVramChart
                        width={width}
                        vramDayOffset={vramDayOffset}
                        setVramDayOffset={setVramDayOffset}
                        fetchVramStats={fetchVramStats}
                        isVramLoading={isVramLoading}
                        vramError={vramError}
                        vramDataByProvider={vramRawDataByProvider}
                        providerMetaByName={vramProviderMetaByName}
                        vramBaseline={vramBaseline}
                        vramBucketSizeSec={vramBucketSizeSec}
                        vramTotalBuckets={vramTotalBuckets}
                        getProviderColor={getProviderColor}
                        nowMs={nowMs}
                        laneStateByProvider={lanesByProvider}
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
              </View>
            </View>

            {/* Row 3: Distribution row — Request type / Model share / Status */}
            <View className="w-full" style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "stretch", columnGap: 16, rowGap: 16 }}>
              <View className="w-full" style={{ flexGrow: 1, flexShrink: 1, flexBasis: 0, minWidth: 280 }}>
                <ChartCard title="Request type" subtitle="Cloud vs local share.">
                  {(width) => {
                    if (!statsReady) {
                      return <DonutSkeleton diameter={180} legendItems={2} centerRows={2} />;
                    }
                    if (!providerPieData.length) {
                      return <EmptyState message="No requests in range." />;
                    }
                    if (usePlotlyWeb) {
                      return (
                        <View style={{ alignItems: "center" }}>
                          <PlotlyPieChart
                            data={providerPieData}
                            width={width}
                            height={240}
                            legendPosition="bottom"
                            hoverValueSuffix=" requests"
                            hoverValueDecimals={0}
                            centerText={{
                              top: "cloud",
                              middle: `${cloudPct}%`,
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
                            className="absolute rounded-full bg-background-0"
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
              <View className="w-full" style={{ flexGrow: 1, flexShrink: 1, flexBasis: 0, minWidth: 280 }}>
                <ChartCard
                  title="Model share"
                  subtitle="Top models in the selected range."
                >
                  {(width) => {
                    if (!statsReady) {
                      return <DonutSkeleton diameter={180} legendItems={3} centerRows={2} />;
                    }
                    if (!modelPieData.length) {
                      return <EmptyState message="No requests in range." />;
                    }
                    if (usePlotlyWeb) {
                      return (
                        <View style={{ alignItems: "center" }}>
                          <PlotlyPieChart
                            data={modelPieData}
                            width={width}
                            height={240}
                            legendPosition="bottom"
                            hoverValueSuffix=" requests"
                            hoverValueDecimals={0}
                            centerText={{
                              top: "models",
                              middle: `${modelPieData.length}`,
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
                            className="absolute rounded-full bg-background-0"
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
              <View className="w-full" style={{ flexGrow: 1, flexShrink: 1, flexBasis: 0, minWidth: 280 }}>
                <ChartCard title="Status" subtitle="Outcome of requests in range.">
                  {() =>
                    !statsReady ? (
                      <StatusPanelSkeleton />
                    ) : statusTotalCount === 0 ? (
                      <EmptyState message="No requests in range." />
                    ) : (
                      <VStack space="md">
                        {statusEntries.map((row) => {
                          const pct =
                            statusTotalCount > 0
                              ? (row.value / statusTotalCount) * 100
                              : 0;
                          return (
                            <VStack key={row.key} className="gap-1">
                              <HStack className="items-center justify-between">
                                <HStack className="items-center" style={{ columnGap: 8 }}>
                                  <View
                                    style={{
                                      height: 8,
                                      width: 8,
                                      borderRadius: 99,
                                      backgroundColor: row.color,
                                    }}
                                  />
                                  <Text
                                    className="text-typography-900"
                                    style={{ fontSize: 12 }}
                                  >
                                    {row.label}
                                  </Text>
                                </HStack>
                                <Text className="text-typography-900" style={{ fontSize: 12 }}>
                                  {row.value.toLocaleString()}{" "}
                                  <Text className="text-typography-400">
                                    · {pct.toFixed(1)}%
                                  </Text>
                                </Text>
                              </HStack>
                              <View
                                className="overflow-hidden rounded-full bg-secondary-200"
                                style={{ height: 6, width: "100%" }}
                              >
                                <View
                                  className="h-full rounded-full"
                                  style={{
                                    width: `${Math.min(100, pct)}%`,
                                    backgroundColor: row.color,
                                  }}
                                />
                              </View>
                            </VStack>
                          );
                        })}
                      </VStack>
                    )
                  }
                </ChartCard>
              </View>
            </View>
          </VStack>
        )}
      </VStack>
    </View>
  );
}
