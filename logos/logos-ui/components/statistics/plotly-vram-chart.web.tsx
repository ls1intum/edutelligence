import React, { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, View } from "react-native";

import { Text } from "@/components/ui/text";
import EmptyState from "@/components/statistics/empty-state";
import { loadPlotly } from "@/components/statistics/plotly-loader.web";
import SegmentedSwitch from "@/components/statistics/segmented-switch";
import { useDarkMode } from "@/components/statistics/use-dark-mode";
import type { LaneSignalData } from "@/components/statistics/types";

/* ================================================================== *
 *  Types                                                              *
 * ================================================================== */

type PlotlyVramChartProps = {
  width: number;
  vramDayOffset: number;
  setVramDayOffset: (offset: number) => void;
  fetchVramStats: (options?: { silent?: boolean }) => void;
  isVramLoading: boolean;
  vramError: string | null;
  vramDataByProvider: { [url: string]: any[] };
  providerMetaByName?: {
    [name: string]: {
      connected?: boolean;
      connection_state?: string;
      runtime_modes?: string[];
    };
  };
  vramBaseline: any[];
  vramBucketSizeSec: number;
  vramTotalBuckets: number;
  getProviderColor: (index: number) => string;
  nowMs: number;
  /** Per-lane state data keyed by provider name then lane_id — used to render lane VRAM traces */
  laneStateByProvider?: Record<string, Record<string, LaneSignalData>>;
};

type VramPoint = {
  ts: number;
  freeGb: number;
  usedGb: number;
  modelsLoaded: number;
  modelNames: string;
};

type ProviderSeries = {
  name: string;
  color: string;
  points: VramPoint[];
  connected: boolean;
  runtimeModes: string[];
};

/* ================================================================== *
 *  Constants & helpers                                                *
 * ================================================================== */

const FUTURE_GAP_THRESHOLD_MS = 30_000;
/** In live mode, show the last N minutes */
const LIVE_WINDOW_MINUTES = 30;
const LIVE_WINDOW_MS = LIVE_WINDOW_MINUTES * 60 * 1000;
const LIVE_RIGHT_PAD_MS = 60_000;
/** When the newest sample is older than this, anchor the live window to
 *  the data instead of wall-clock time — otherwise the trailing window
 *  outruns the data and the chart looks empty. */
const LIVE_STALENESS_LIMIT_MS = 5 * 60 * 1000;

function toNumber(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatAgeShort(ms: number): string {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

function toGbFromMb(value: unknown): number | null {
  const mb = toNumber(value);
  return mb == null ? null : mb / 1024;
}

function toGbFromBytes(value: unknown): number | null {
  const bytes = toNumber(value);
  return bytes == null ? null : bytes / 1_000_000_000;
}

function formatLoadedModels(raw: any): string {
  if (!Array.isArray(raw?.loaded_models)) {
    const names = Array.isArray(raw?.loaded_model_names) ? raw.loaded_model_names : [];
    return names.join(", ");
  }

  return raw.loaded_models
    .map((model: any) => {
      const name = model?.name ?? model?.model;
      if (!name) return null;
      const sizeGb =
        toGbFromBytes(model?.size_vram) ??
        toGbFromMb(model?.size_vram_mb) ??
        toGbFromBytes(model?.size) ??
        toGbFromMb(model?.size_mb);
      return sizeGb != null && sizeGb > 0
        ? `${name} (${sizeGb.toFixed(2)} GB)`
        : String(name);
    })
    .filter((value: string | null): value is string => Boolean(value))
    .join(", ");
}

function withAlpha(color: string, alpha: number): string {
  if (!color.startsWith("#")) return color;
  const hex = color.slice(1);
  const normalized =
    hex.length === 3
      ? hex
          .split("")
          .map((part) => `${part}${part}`)
          .join("")
      : hex;
  if (normalized.length !== 6) return color;
  const r = Number.parseInt(normalized.slice(0, 2), 16);
  const g = Number.parseInt(normalized.slice(2, 4), 16);
  const b = Number.parseInt(normalized.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function normalizeProviderPoints(rawPoints: any[]): VramPoint[] {
  const points: VramPoint[] = [];

  for (const raw of rawPoints || []) {
    if (!raw || raw._empty) continue;

    const ts =
      typeof raw.timestamp === "number"
        ? raw.timestamp
        : new Date(raw.timestamp ?? "").getTime();
    if (!Number.isFinite(ts)) continue;

    const freeGb =
      toNumber(raw.remaining_vram_gb) ??
      toGbFromMb(raw.remaining_vram_mb) ??
      toNumber(raw.value);
    if (freeGb == null) continue;

    const usedGb =
      toNumber(raw.used_vram_gb) ??
      toGbFromMb(raw.used_vram_mb) ??
      toGbFromMb(raw.vram_mb) ??
      0;

    const modelsLoaded = toNumber(raw.models_loaded) ?? 0;
    const modelNames = formatLoadedModels(raw);

    points.push({
      ts,
      freeGb,
      usedGb,
      modelsLoaded,
      modelNames,
    });
  }

  points.sort((a, b) => a.ts - b.ts);

  const deduped: VramPoint[] = [];
  let lastTs = -1;
  for (const point of points) {
    if (point.ts === lastTs) {
      deduped[deduped.length - 1] = point;
    } else {
      deduped.push(point);
      lastTs = point.ts;
    }
  }
  return deduped;
}

function computeVisibleYRange(
  seriesList: VramPoint[][],
  startMs: number,
  endMs: number,
): [number, number] | null {
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;

  for (const series of seriesList) {
    for (const point of series) {
      if (point.ts < startMs || point.ts > endMs) continue;
      if (point.freeGb < minY) minY = point.freeGb;
      if (point.freeGb > maxY) maxY = point.freeGb;
    }
  }

  if (!Number.isFinite(minY) || !Number.isFinite(maxY)) return null;
  if (minY === maxY) {
    const pad = Math.max(Math.abs(maxY) * 0.1, 0.25);
    return [0, maxY + pad];
  }
  const pad = (maxY - minY) * 0.08;
  return [0, maxY + pad];
}

/* ================================================================== *
 *  Component                                                          *
 * ================================================================== */

export default function PlotlyVramChart({
  width,
  fetchVramStats,
  isVramLoading,
  vramError,
  vramDataByProvider,
  providerMetaByName = {},
  getProviderColor,
  nowMs,
  laneStateByProvider,
}: PlotlyVramChartProps) {
  const plotRef = useRef<HTMLDivElement | null>(null);
  const plotlyRef = useRef<any>(null);
  const initializedRef = useRef(false);
  const relayoutHandlerRef = useRef<any>(null);
  const isProgrammaticRelayoutRef = useRef(false);
  const userLockedRangeRef = useRef(false);
  const providerOrderRef = useRef<string[]>([]);
  const prevFirstTsRef = useRef<number | null>(null);
  const prevLengthsRef = useRef<number[]>([]);
  const prevLaneLengthsRef = useRef<Record<string, number>>({});
  const laneKeyOrderRef = useRef<string>("");
  const prevYRangeRef = useRef<[number, number] | null>(null);
  const [plotlyError, setPlotlyError] = useState<string | null>(null);
  const [plotlyReady, setPlotlyReady] = useState(false);
  const isDark = useDarkMode();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const hoverHandlerRef = useRef<any>(null);
  const unhoverHandlerRef = useRef<any>(null);
  const [hoverTooltip, setHoverTooltip] = useState<{
    visible: boolean;
    left: number;
    top: number;
    title: string;
    free: number;
    total: number;
    modelsLoaded: number;
    providerName: string;
    providerColor: string;
  }>({
    visible: false,
    left: 0,
    top: 0,
    title: "",
    free: 0,
    total: 0,
    modelsLoaded: 0,
    providerName: "",
    providerColor: "",
  });

  /** Live mode: the chart auto-scrolls to follow the latest data, showing
   *  a trailing window centred on the newest point. Turning it off lets
   *  the user freely zoom/pan; incoming data is still appended but the
   *  viewport stays put. */
  const [liveMode, setLiveMode] = useState(true);
  const liveModeRef = useRef(liveMode);
  liveModeRef.current = liveMode;

  /* ── Derived series ────────────────────────────────────────────────── */
  const providers = useMemo(
    () => Object.keys(vramDataByProvider),
    [vramDataByProvider],
  );

  const providerSeries = useMemo<ProviderSeries[]>(
    () =>
      providers.map((name, idx) => {
        const meta = providerMetaByName[name] || {};
        const connected =
          meta.connection_state === "offline" || meta.connected === false
            ? false
            : true;
        return {
          name,
          color: getProviderColor(idx),
          points: normalizeProviderPoints(vramDataByProvider[name] || []),
          connected,
          runtimeModes: Array.isArray(meta.runtime_modes) ? meta.runtime_modes : [],
        };
      }),
    [providers, providerMetaByName, vramDataByProvider, getProviderColor],
  );

  /* ── Lane entries ──────────────────────────────────────────────────── *
   * Per-lane time series have been disabled in this chart (laneTraces is
   * always empty). We previously iterated every sample × every lane on
   * every render to build full lane series — wasted work that scaled with
   * a full day of telemetry. Now we only collect the current lane keys
   * from the latest snapshot to keep the cache-invalidation key stable.
   */
  const laneEntries = useMemo(() => {
    if (!laneStateByProvider) return [];
    const entries: Array<{ key: string; points: Array<{ ts: number; vramMb: number }> }> = [];
    for (const providerName of providers) {
      const lanes = laneStateByProvider[providerName] ?? {};
      for (const laneId of Object.keys(lanes)) {
        entries.push({ key: `${providerName}::${laneId}`, points: [] });
      }
    }
    return entries.sort((a, b) => a.key.localeCompare(b.key));
  }, [laneStateByProvider, providers]);

  const hasAnyPoints = providerSeries.some((p) => p.points.length > 0);

  const minTs = hasAnyPoints
    ? Math.min(
        ...providerSeries
          .filter((p) => p.points.length > 0)
          .map((p) => p.points[0].ts),
      )
    : null;

  const latestDataTs = hasAnyPoints
    ? Math.max(
        ...providerSeries
          .filter((p) => p.points.length > 0)
          .map((p) => p.points[p.points.length - 1].ts),
      )
    : null;

  const showFutureGap =
    latestDataTs != null && nowMs - latestDataTs > FUTURE_GAP_THRESHOLD_MS;

  /* ── X-axis range helpers ──────────────────────────────────────────── */

  /** Full-history range: all data + a little padding to the right. */
  const fullXRange = useMemo<[Date, Date] | null>(() => {
    if (minTs == null || latestDataTs == null) return null;
    const dataEndTs = Math.max(nowMs, latestDataTs);
    const spanMs = Math.max(dataEndTs - minTs, 60_000);
    const rightPad = Math.max(Math.floor(spanMs * 0.04), 90_000);
    return [new Date(minTs), new Date(dataEndTs + rightPad)];
  }, [latestDataTs, minTs, nowMs]);

  /** Live range: trailing window anchored to the right edge.
   *  Normally that edge tracks wall-clock time so new samples appear at
   *  the right; when the newest sample is far in the past (provider
   *  offline, server paused) we anchor to the data instead so the line
   *  stays visible — the "Last sample" badge already advertises staleness. */
  const liveXRange = useMemo<[Date, Date] | null>(() => {
    if (latestDataTs == null) return null;
    const isStale = nowMs - latestDataTs > LIVE_STALENESS_LIMIT_MS;
    const anchor = isStale ? latestDataTs : Math.max(nowMs, latestDataTs);
    const end = anchor + LIVE_RIGHT_PAD_MS;
    const start = end - LIVE_WINDOW_MS;
    return [new Date(start), new Date(end)];
  }, [latestDataTs, nowMs]);

  /* ── Traces ────────────────────────────────────────────────────────── */
  const traces = useMemo(
    () =>
      providerSeries.map((provider) => ({
        type: "scatter" as const,
        // lines+markers so a fresh provider with a single sample is
        // visible (scatter `lines` alone draws nothing for a 1-point
        // trace). Markers are small and `connectgaps: false` keeps
        // them suppressed where the line truly has gaps.
        mode: "lines+markers" as const,
        name:
          provider.runtimeModes.length === 1
            ? `${provider.name} [${provider.runtimeModes[0]}]${provider.connected ? "" : " (offline)"}`
            : `${provider.name}${provider.connected ? "" : " (offline)"}`,
        x: provider.points.map((pt) => new Date(pt.ts)),
        y: provider.points.map((pt) => pt.freeGb),
        line: {
          color: provider.connected ? provider.color : withAlpha(provider.color, 0.35),
          width: 1.8,
          // Step shape (hold-then-jump). VRAM allocations are abrupt:
          // a lane wake bumps usage by GBs in one sample. A spline would
          // smooth that into a fake ramp; "hv" matches nvtop and tells
          // the truth about when each transition actually happened.
          shape: "hv" as const,
        },
        marker: {
          size: provider.points.length <= 2 ? 6 : 3,
          color: provider.connected ? provider.color : withAlpha(provider.color, 0.35),
          line: { width: 0 },
        },
        fill: "tozeroy" as const,
        fillcolor: provider.connected
          ? `${provider.color}29`
          : withAlpha(provider.color, 0.08),
        opacity: provider.connected ? 1 : 0.55,
        connectgaps: false,
        customdata: provider.points.map((pt) => [
          pt.usedGb,
          pt.freeGb,
          pt.modelsLoaded,
          pt.modelNames,
        ]),
        // Default plotly tooltip is suppressed; we render a custom HTML
        // tooltip via plotly_hover for consistency with the volume chart.
        hoverinfo: "none",
      })),
    [providerSeries],
  );

  /* ── Lane traces removed: per-lane decomposition clutters the chart. ── */
  const laneTraces = useMemo(() => [] as any[], []);

  /* ── Combined traces ────────────────────────────────────────────────── */
  const allTraces = useMemo(() => [...traces, ...laneTraces], [traces, laneTraces]);

  /* ── Load Plotly CDN ───────────────────────────────────────────────── */
  useEffect(() => {
    let cancelled = false;
    loadPlotly()
      .then((plotly) => {
        if (cancelled) return;
        plotlyRef.current = plotly;
        setPlotlyReady(true);
      })
      .catch((err) => {
        if (cancelled) return;
        setPlotlyError(
          err instanceof Error ? err.message : "Failed to load Plotly.",
        );
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /* ── Main render / update effect ───────────────────────────────────── */
  useEffect(() => {
    let disposed = false;

    const renderPlot = async () => {
      if (
        !plotlyReady ||
        !plotRef.current ||
        !plotlyRef.current ||
        !traces.length ||
        minTs == null
      )
        return;

      const plotly = plotlyRef.current;
      const graphDiv = plotRef.current;
      const providerOrder = providerSeries.map((p) => p.name);
      const firstTs =
        providerSeries.find((p) => p.points.length > 0)?.points[0]?.ts ?? null;

      /* Decide which x-range to show */
      const chooseXRange = (): [Date, Date] | undefined => {
        // In Live mode the trailing window must follow data on every render,
        // even if the user previously panned/zoomed. Otherwise a single drag
        // of the rangeslider locks the viewport away from the data and the
        // chart looks empty. Locked ranges only matter in Full History mode.
        if (liveModeRef.current && liveXRange) return liveXRange;
        if (userLockedRangeRef.current) return undefined; // keep user's viewport
        if (fullXRange) return fullXRange;
        return undefined;
      };

      const xRange = chooseXRange();
      const fullEnd = fullXRange ? fullXRange[1].getTime() : nowMs;

      // Dark mode colors
      const textMuted = isDark ? "#94A3B8" : "#64748B";
      const gridColor = isDark ? "rgba(255,255,255,0.06)" : "rgba(15,23,42,0.06)";
      const zeroLine = isDark ? "rgba(255,255,255,0.10)" : "rgba(15,23,42,0.10)";
      const legendColor = isDark ? "#CBD5E1" : "#1E293B";
      const futureGapFill = isDark ? "rgba(148,163,184,0.08)" : "rgba(148,163,184,0.14)";

      const layout: Record<string, any> = {
        width,
        height: 320,
        margin: { l: 44, r: 16, t: 18, b: 40 },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        // Zoom is undone in the relayout handler, not via fixedrange (both
        // axes fixed would kill the hover layer / tooltips).
        dragmode: "zoom",
        uirevision: "vram-remaining-v3",
        hovermode: "closest",
        xaxis: {
          type: "date",
          fixedrange: false, // keep false, else the hover layer (tooltips) dies
          showgrid: true,
          gridcolor: gridColor,
          tickfont: { color: textMuted, size: 10 },
          rangeslider: { visible: false },
          ...(xRange ? { range: xRange } : {}),
        },
        yaxis: {
          fixedrange: true,
          showgrid: true,
          gridcolor: gridColor,
          zerolinecolor: zeroLine,
          tickfont: { color: textMuted, size: 10 },
          rangemode: "tozero",
        },
        showlegend: false,
        legend: { orientation: "h", x: 0, y: 1.16, font: { color: legendColor } },
        hoverlabel: {
          bgcolor: isDark ? "#1E293B" : "#FFFFFF",
          font: {
            color: isDark ? "#F1F5F9" : "#1E293B",
            size: 13,
          },
          namelength: -1,
        },
        shapes:
          showFutureGap && latestDataTs != null
            ? [
                {
                  type: "rect",
                  x0: new Date(latestDataTs),
                  x1: new Date(fullEnd),
                  y0: 0,
                  y1: 1,
                  yref: "paper",
                  fillcolor: futureGapFill,
                  line: { width: 0 },
                },
              ]
            : [],
        annotations:
          showFutureGap && latestDataTs != null
            ? [
                {
                  x: new Date((latestDataTs + fullEnd) / 2),
                  y: 1,
                  yref: "paper",
                  text: "Waiting for next sample …",
                  showarrow: false,
                  yshift: -12,
                  font: { size: 11, color: textMuted },
                },
              ]
            : [],
      };

      const config = {
        responsive: true,
        displaylogo: false,
        displayModeBar: false,
        scrollZoom: false,
      };

      /* ── Incremental-update detection ──────────────────────────────── */
      const currentLaneKeyOrder = laneEntries.map((e) => e.key).join("|");
      const canAppend =
        initializedRef.current &&
        prevFirstTsRef.current === firstTs &&
        providerOrder.join("|") === providerOrderRef.current.join("|") &&
        prevLengthsRef.current.length === providerSeries.length &&
        laneKeyOrderRef.current === currentLaneKeyOrder &&
        providerSeries.every(
          (p, i) => p.points.length >= (prevLengthsRef.current[i] || 0),
        );
      const hasNewPoints =
        canAppend &&
        (providerSeries.some(
          (p, i) => p.points.length > (prevLengthsRef.current[i] || 0),
        ) ||
          laneEntries.some(
            (e) => e.points.length > (prevLaneLengthsRef.current[e.key] || 0),
          ));

      /* ── y-auto-fit (with jitter guard) ────────────────────────────── */
      const updateVisibleYRange = async (start: Date, end: Date) => {
        const range = computeVisibleYRange(
          providerSeries.map((p) => p.points),
          start.getTime(),
          end.getTime(),
        );
        if (!range) return;

        const prev = prevYRangeRef.current;
        if (prev) {
          const span = Math.max(prev[1] - prev[0], range[1] - range[0], 0.01);
          const drift =
            Math.abs(range[0] - prev[0]) + Math.abs(range[1] - prev[1]);
          if (drift / span < 0.02) return; // < 2% drift → skip
        }
        prevYRangeRef.current = range;

        isProgrammaticRelayoutRef.current = true;
        try {
          await plotly.relayout(graphDiv, { "yaxis.range": range });
        } finally {
          isProgrammaticRelayoutRef.current = false;
        }
      };

      /* ── First render ──────────────────────────────────────────────── */
      if (!initializedRef.current) {
        isProgrammaticRelayoutRef.current = true;
        try {
          await plotly.newPlot(graphDiv, allTraces, layout, config);
        } finally {
          isProgrammaticRelayoutRef.current = false;
        }

        relayoutHandlerRef.current = (ev: Record<string, any>) => {
          if (isProgrammaticRelayoutRef.current) return;

          if (ev["xaxis.autorange"]) {
            userLockedRangeRef.current = false;
            prevYRangeRef.current = null;
            // Snapping back to auto → decide based on liveMode
            const resetRange = liveModeRef.current && liveXRange ? liveXRange : fullXRange;
            if (resetRange) {
              isProgrammaticRelayoutRef.current = true;
              plotly
                .relayout(graphDiv, { "xaxis.range": resetRange })
                .finally(() => {
                  isProgrammaticRelayoutRef.current = false;
                  void updateVisibleYRange(resetRange[0], resetRange[1]);
                });
            }
            return;
          }

          const start = ev["xaxis.range[0]"];
          const end = ev["xaxis.range[1]"];
          if (start && end) {
            // Zoom disabled: snap back to the toggle-driven range instead of locking.
            userLockedRangeRef.current = false;
            const resetRange =
              liveModeRef.current && liveXRange ? liveXRange : fullXRange;
            if (resetRange) {
              isProgrammaticRelayoutRef.current = true;
              plotly
                .relayout(graphDiv, { "xaxis.range": resetRange })
                .finally(() => {
                  isProgrammaticRelayoutRef.current = false;
                  void updateVisibleYRange(resetRange[0], resetRange[1]);
                });
            }
          }
        };
        (graphDiv as any).on("plotly_relayout", relayoutHandlerRef.current);

        hoverHandlerRef.current = (ev: any) => {
          const points = Array.isArray(ev?.points) ? ev.points : [];
          if (!points.length) return;
          const pt = points[0];
          const cd = pt?.customdata;
          if (!Array.isArray(cd)) return;
          const [usedGb, freeGb, modelsLoaded] = cd;
          const xMs = new Date(pt?.x).getTime();
          if (!Number.isFinite(xMs)) return;
          const containerRect = containerRef.current?.getBoundingClientRect();
          const clientX = Number(ev?.event?.clientX);
          const clientY = Number(ev?.event?.clientY);
          if (!containerRect || !Number.isFinite(clientX) || !Number.isFinite(clientY)) return;
          const W = 240;
          const H = 92;
          let left = clientX - containerRect.left + 14;
          let top = clientY - containerRect.top + 14;
          if (left + W > containerRect.width - 8) left = clientX - containerRect.left - W - 14;
          if (top + H > containerRect.height - 8) top = clientY - containerRect.top - H - 14;
          const tFmt = new Date(xMs);
          const title = `${tFmt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })}`;
          const providerName = String(pt?.fullData?.name || "").replace(/\s*\[[^\]]*\]\s*/g, "").trim();
          const providerColor =
            (typeof pt?.fullData?.line?.color === "string" ? pt.fullData.line.color : "") || "#94A3B8";
          setHoverTooltip({
            visible: true,
            left: Math.max(8, left),
            top: Math.max(8, top),
            title,
            free: Number(freeGb) || 0,
            total: (Number(usedGb) || 0) + (Number(freeGb) || 0),
            modelsLoaded: Number(modelsLoaded) || 0,
            providerName,
            providerColor,
          });
        };
        unhoverHandlerRef.current = () => {
          setHoverTooltip((prev) => (prev.visible ? { ...prev, visible: false } : prev));
        };
        (graphDiv as any).on("plotly_hover", hoverHandlerRef.current);
        (graphDiv as any).on("plotly_unhover", unhoverHandlerRef.current);

        initializedRef.current = true;
      } else if (canAppend) {
        /* ── Incremental append ──────────────────────────────────────── */
        if (hasNewPoints) {
          const extendX: Date[][] = [];
          const extendY: number[][] = [];
          const extendCD: any[][] = [];
          const indices: number[] = [];

          providerSeries.forEach((p, idx) => {
            const prevLen = prevLengthsRef.current[idx] || 0;
            const newPts = p.points.slice(prevLen);
            if (!newPts.length) return;

            indices.push(idx);
            extendX.push(newPts.map((pt) => new Date(pt.ts)));
            extendY.push(newPts.map((pt) => pt.freeGb));
            extendCD.push(
              newPts.map((pt) => [
                pt.usedGb,
                pt.freeGb,
                pt.modelsLoaded,
                pt.modelNames,
              ]),
            );
          });

          // Also extend lane traces
          const laneStartIdx = providerSeries.length;
          laneEntries.forEach((entry, laneIdx) => {
            const prevLen = prevLaneLengthsRef.current[entry.key] || 0;
            const newPts = entry.points.slice(prevLen);
            if (!newPts.length) return;
            indices.push(laneStartIdx + laneIdx);
            extendX.push(newPts.map((pt) => new Date(pt.ts)));
            extendY.push(newPts.map((pt) => pt.vramMb / 1024));
            extendCD.push(newPts.map((pt) => [entry.runtimeState, entry.modelName, pt.vramMb]));
          });

          if (indices.length > 0) {
            await plotly.extendTraces(
              graphDiv,
              { x: extendX, y: extendY, customdata: extendCD },
              indices,
            );
          }
        }

        /* Update shapes + x-range. In Live mode we always push the
         * trailing window even if the user previously panned, otherwise
         * the viewport gets stranded away from incoming data. */
        const relayoutPayload: Record<string, any> = {
          shapes: layout.shapes,
          annotations: layout.annotations,
        };
        if (xRange && (liveModeRef.current || !userLockedRangeRef.current)) {
          relayoutPayload["xaxis.range"] = xRange;
        }
        isProgrammaticRelayoutRef.current = true;
        try {
          await plotly.relayout(graphDiv, relayoutPayload);
        } finally {
          isProgrammaticRelayoutRef.current = false;
        }
      } else {
        /* ── Full redraw (providers changed, lane set changed, etc.) ─── */
        isProgrammaticRelayoutRef.current = true;
        try {
          await plotly.react(graphDiv, allTraces, layout, config);
        } finally {
          isProgrammaticRelayoutRef.current = false;
        }
        // plotly.react preserves the user's view state when uirevision
        // matches — which means the new layout's xaxis.range is ignored.
        // In live mode that breaks the trailing-window behaviour: new
        // samples arrive but the visible range stays anchored to the
        // first render. Push the range explicitly via relayout, which
        // is not gated by uirevision.
        if (xRange && (liveModeRef.current || !userLockedRangeRef.current)) {
          isProgrammaticRelayoutRef.current = true;
          try {
            await plotly.relayout(graphDiv, { "xaxis.range": xRange });
          } finally {
            isProgrammaticRelayoutRef.current = false;
          }
        }
      }

      /* ── Auto-fit y-axis ───────────────────────────────────────────── */
      const currentXRange = (graphDiv as any)?.layout?.xaxis?.range;
      if (Array.isArray(currentXRange) && currentXRange.length === 2) {
        await updateVisibleYRange(
          new Date(currentXRange[0]),
          new Date(currentXRange[1]),
        );
      } else if (xRange) {
        await updateVisibleYRange(xRange[0], xRange[1]);
      }

      if (disposed) return;
      providerOrderRef.current = providerOrder;
      prevFirstTsRef.current = firstTs;
      prevLengthsRef.current = providerSeries.map((p) => p.points.length);
      laneKeyOrderRef.current = currentLaneKeyOrder;
      for (const entry of laneEntries) {
        prevLaneLengthsRef.current[entry.key] = entry.points.length;
      }
    };

    renderPlot().catch((err) => {
      if (disposed) return;
      setPlotlyError(
        err instanceof Error ? err.message : "Failed to render VRAM chart.",
      );
    });

    return () => {
      disposed = true;
    };
  }, [
    allTraces,
    traces,
    laneTraces,
    laneEntries,
    providerSeries,
    width,
    nowMs,
    minTs,
    latestDataTs,
    showFutureGap,
    fullXRange,
    liveXRange,
    liveMode,
    isDark,
    plotlyReady,
  ]);

  /* ── Cleanup on unmount ────────────────────────────────────────────── */
  useEffect(() => {
    const graphDiv = plotRef.current;
    return () => {
      if (!graphDiv || !plotlyRef.current) return;
      try {
        if (relayoutHandlerRef.current) {
          (graphDiv as any).removeListener(
            "plotly_relayout",
            relayoutHandlerRef.current,
          );
        }
        if (hoverHandlerRef.current) {
          (graphDiv as any).removeListener("plotly_hover", hoverHandlerRef.current);
        }
        if (unhoverHandlerRef.current) {
          (graphDiv as any).removeListener("plotly_unhover", unhoverHandlerRef.current);
        }
        plotlyRef.current.purge(graphDiv);
      } catch {
        // no-op
      }
    };
  }, []);

  /* ── Toggle callbacks ─────────────────────────────────────────────── */
  const handleSetLiveMode = (next: boolean) => {
    setLiveMode(next);
    if (next) {
      // Turning live ON → unlock user range so the chart snaps to live window
      userLockedRangeRef.current = false;
      prevYRangeRef.current = null;
    }
  };

  /* ================================================================== *
   *  Render                                                             *
   * ================================================================== */

  const sampleAgeMs =
    latestDataTs != null ? Math.max(0, nowMs - latestDataTs) : null;
  const isStale =
    sampleAgeMs != null && sampleAgeMs > LIVE_STALENESS_LIMIT_MS;

  const controls = (
    <View className="mb-3 flex-row flex-wrap items-center gap-2">
      <SegmentedSwitch
        value={liveMode}
        onChange={(next) => handleSetLiveMode(Boolean(next))}
        options={[
          { value: true, label: `Live (${LIVE_WINDOW_MINUTES}m)` },
          { value: false, label: "Full History" },
        ]}
      />

      {liveMode && latestDataTs != null && (
        <Text
          className={
            isStale
              ? "text-xs font-semibold text-warning-600"
              : "text-xs font-semibold text-indicator-info"
          }
        >
          Last sample:{" "}
          {new Date(latestDataTs).toLocaleTimeString("en-GB", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            timeZone: "UTC",
          })}{" "}
          UTC
          {isStale && sampleAgeMs != null
            ? ` · stale (${formatAgeShort(sampleAgeMs)})`
            : ""}
        </Text>
      )}
    </View>
  );

  if (isVramLoading) {
    return (
      <View>
        {controls}
        <View
          style={{
            height: 220,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
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

  if (!providers.length) {
    return (
      <View>
        {controls}
        <EmptyState message="No VRAM provider data available." />
      </View>
    );
  }

  if (!hasAnyPoints) {
    return (
      <View>
        {controls}
        <View style={{ gap: 12 }}>
          <EmptyState message="Providers detected, but no live memory samples are available yet." />
          <View style={{ gap: 8 }}>
            {providerSeries.map((provider) => (
              <View
                key={provider.name}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 10,
                  opacity: provider.connected ? 1 : 0.5,
                }}
              >
                <View
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: 5,
                    backgroundColor: provider.connected
                      ? provider.color
                      : withAlpha(provider.color, 0.35),
                  }}
                />
                <Text className="text-sm text-typography-700">
                  {provider.name}
                  {provider.runtimeModes.length === 1
                    ? ` [${provider.runtimeModes[0]}]`
                    : ""}
                  {provider.connected ? "" : " (offline)"}
                </Text>
              </View>
            ))}
          </View>
        </View>
      </View>
    );
  }

  if (plotlyError) {
    return (
      <View>
        {controls}
        <EmptyState message={plotlyError} />
      </View>
    );
  }

  return (
    <View>
      {controls}
      <div ref={containerRef} style={{ position: "relative", width: "100%" }}>
        <div ref={plotRef} style={{ width: "100%", height: 320 }} />
        {hoverTooltip.visible && (
          <div
            style={{
              position: "absolute",
              left: hoverTooltip.left,
              top: hoverTooltip.top,
              pointerEvents: "none",
              zIndex: 30,
              minWidth: 200,
              maxWidth: 260,
              border: `1px solid ${isDark ? "rgba(148,163,184,0.25)" : "rgba(15,23,42,0.12)"}`,
              background: isDark ? "rgba(15,23,42,0.96)" : "rgba(255,255,255,0.98)",
              color: isDark ? "#F8FAFC" : "#0F172A",
              borderRadius: 10,
              boxShadow: isDark
                ? "0 8px 24px rgba(0,0,0,0.45), 0 1px 0 rgba(255,255,255,0.04) inset"
                : "0 8px 24px rgba(15,23,42,0.12)",
              padding: "8px 12px",
              fontFamily: "inherit",
            }}
          >
            <div
              style={{
                fontSize: 11,
                lineHeight: "16px",
                fontWeight: 500,
                marginBottom: 6,
                letterSpacing: 0.2,
                color: isDark ? "#94A3B8" : "#475569",
                textTransform: "uppercase",
              }}
            >
              {hoverTooltip.title}
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 13,
                lineHeight: "20px",
                marginBottom: 2,
              }}
            >
              <div
                style={{
                  width: 10,
                  height: 10,
                  backgroundColor: hoverTooltip.providerColor,
                  borderRadius: 3,
                  flexShrink: 0,
                }}
              />
              <span style={{ fontWeight: 600 }}>
                {hoverTooltip.providerName.split("/").slice(-1)[0] || hoverTooltip.providerName}
              </span>
            </div>
            <div style={{ fontSize: 12.5, lineHeight: "18px" }}>
              <span style={{ opacity: 0.7 }}>Free</span>{" "}
              <span style={{ fontWeight: 600 }}>{hoverTooltip.free.toFixed(1)}</span>
              <span style={{ opacity: 0.5 }}> / {hoverTooltip.total.toFixed(0)} GB</span>
            </div>
            <div style={{ fontSize: 12.5, lineHeight: "18px" }}>
              <span style={{ opacity: 0.7 }}>Models loaded</span>{" "}
              <span style={{ fontWeight: 600 }}>{hoverTooltip.modelsLoaded}</span>
            </div>
          </div>
        )}
      </div>
    </View>
  );
}
