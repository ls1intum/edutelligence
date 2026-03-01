import React, { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, View } from "react-native";

import { Text } from "@/components/ui/text";
import EmptyState from "@/components/statistics/empty-state";
import { loadPlotly } from "@/components/statistics/plotly-loader.web";
import SegmentedSwitch from "@/components/statistics/segmented-switch";
import { useDarkMode } from "@/components/statistics/use-dark-mode";

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
  vramBaseline: any[];
  vramBucketSizeSec: number;
  vramTotalBuckets: number;
  getProviderColor: (index: number) => string;
  nowMs: number;
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
};

/* ================================================================== *
 *  Constants & helpers                                                *
 * ================================================================== */

const FUTURE_GAP_THRESHOLD_MS = 30_000;
/** In live mode, show the last N minutes */
const LIVE_WINDOW_MINUTES = 30;
const LIVE_WINDOW_MS = LIVE_WINDOW_MINUTES * 60 * 1000;
const LIVE_RIGHT_PAD_MS = 60_000;

function toNumber(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function toGbFromMb(value: unknown): number | null {
  const mb = toNumber(value);
  return mb == null ? null : mb / 1024;
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
    const namesFromList = Array.isArray(raw.loaded_model_names)
      ? raw.loaded_model_names
      : Array.isArray(raw.loaded_models)
        ? raw.loaded_models
            .map((m: any) => m?.name ?? m?.model)
            .filter((name: string | undefined) => !!name)
        : [];

    points.push({
      ts,
      freeGb,
      usedGb,
      modelsLoaded,
      modelNames: namesFromList.join(", "),
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
  getProviderColor,
  nowMs,
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
  const prevYRangeRef = useRef<[number, number] | null>(null);
  const [plotlyError, setPlotlyError] = useState<string | null>(null);
  const isDark = useDarkMode();

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
      providers.map((name, idx) => ({
        name,
        color: getProviderColor(idx),
        points: normalizeProviderPoints(vramDataByProvider[name] || []),
      })),
    [providers, vramDataByProvider, getProviderColor],
  );

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

  /** Live range: trailing window centred on the latest data point. */
  const liveXRange = useMemo<[Date, Date] | null>(() => {
    if (latestDataTs == null) return null;
    const end = Math.max(nowMs, latestDataTs) + LIVE_RIGHT_PAD_MS;
    const start = end - LIVE_WINDOW_MS;
    return [new Date(start), new Date(end)];
  }, [latestDataTs, nowMs]);

  /* ── Traces ────────────────────────────────────────────────────────── */
  const traces = useMemo(
    () =>
      providerSeries.map((provider) => ({
        type: "scattergl" as const,
        mode: "lines" as const,
        name: provider.name,
        x: provider.points.map((pt) => new Date(pt.ts)),
        y: provider.points.map((pt) => pt.freeGb),
        line: { color: provider.color, width: 2.8 },
        connectgaps: false,
        customdata: provider.points.map((pt) => [
          pt.usedGb,
          pt.freeGb,
          pt.modelsLoaded,
          pt.modelNames,
        ]),
        hovertemplate:
          "Free: %{customdata[1]:.2f} GB" +
          "<br>Used: %{customdata[0]:.2f} GB" +
          "<br>Models: %{customdata[2]:.0f} — %{customdata[3]}" +
          "<extra>%{fullData.name}</extra>",
      })),
    [providerSeries],
  );

  /* ── Load Plotly CDN ───────────────────────────────────────────────── */
  useEffect(() => {
    let cancelled = false;
    loadPlotly()
      .then((plotly) => {
        if (cancelled) return;
        plotlyRef.current = plotly;
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
        if (userLockedRangeRef.current) return undefined; // keep user's viewport
        if (liveModeRef.current && liveXRange) return liveXRange;
        if (fullXRange) return fullXRange;
        return undefined;
      };

      const xRange = chooseXRange();
      const fullEnd = fullXRange ? fullXRange[1].getTime() : nowMs;

      // Dark mode colors
      const textMuted = isDark ? "#94A3B8" : "#64748B";
      const gridColor = isDark ? "#334155" : "#CBD5E1";
      const zeroLine = isDark ? "#475569" : "#94A3B8";
      const plotBg = isDark ? "rgba(30,41,59,0.5)" : "rgba(15,23,42,0.06)";
      const legendColor = isDark ? "#CBD5E1" : "#1E293B";
      const futureGapFill = isDark ? "rgba(148,163,184,0.08)" : "rgba(148,163,184,0.14)";

      const layout: Record<string, any> = {
        width,
        height: 300,
        margin: { l: 48, r: 16, t: 20, b: 72 },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: plotBg,
        dragmode: "zoom",
        uirevision: "vram-remaining-v3",
        hovermode: "x unified",
        xaxis: {
          type: "date",
          fixedrange: false,
          showgrid: true,
          gridcolor: gridColor,
          tickfont: { color: textMuted, size: 11 },
          title: {
            text: "Time (UTC)",
            font: { color: textMuted, size: 11 },
            standoff: 14,
          },
          rangeslider: {
            visible: true,
            thickness: 0.12,
            bgcolor: isDark ? "rgba(30,41,59,0.8)" : "rgba(241,245,249,0.9)",
            bordercolor: isDark ? "#475569" : "#CBD5E1",
            borderwidth: 1,
          },
          ...(xRange ? { range: xRange } : {}),
        },
        yaxis: {
          fixedrange: true,
          showgrid: true,
          gridcolor: gridColor,
          zerolinecolor: zeroLine,
          tickfont: { color: textMuted, size: 11 },
          rangemode: "tozero",
          title: {
            text: "Remaining VRAM (GB)",
            font: { color: textMuted, size: 11 },
          },
        },
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
      const canAppend =
        initializedRef.current &&
        prevFirstTsRef.current === firstTs &&
        providerOrder.join("|") === providerOrderRef.current.join("|") &&
        prevLengthsRef.current.length === providerSeries.length &&
        providerSeries.every(
          (p, i) => p.points.length >= (prevLengthsRef.current[i] || 0),
        );
      const hasNewPoints =
        canAppend &&
        providerSeries.some(
          (p, i) => p.points.length > (prevLengthsRef.current[i] || 0),
        );

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
          await plotly.newPlot(graphDiv, traces, layout, config);
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
            userLockedRangeRef.current = true;
            void updateVisibleYRange(new Date(start), new Date(end));
          }
        };
        (graphDiv as any).on("plotly_relayout", relayoutHandlerRef.current);
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

          if (indices.length > 0) {
            await plotly.extendTraces(
              graphDiv,
              { x: extendX, y: extendY, customdata: extendCD },
              indices,
            );
          }
        }

        /* Update shapes + x-range (only if not user-locked) */
        const relayoutPayload: Record<string, any> = {
          shapes: layout.shapes,
          annotations: layout.annotations,
        };
        if (!userLockedRangeRef.current && xRange) {
          relayoutPayload["xaxis.range"] = xRange;
        }
        isProgrammaticRelayoutRef.current = true;
        try {
          await plotly.relayout(graphDiv, relayoutPayload);
        } finally {
          isProgrammaticRelayoutRef.current = false;
        }
      } else {
        /* ── Full redraw (providers changed, etc.) ───────────────────── */
        isProgrammaticRelayoutRef.current = true;
        try {
          await plotly.react(graphDiv, traces, layout, config);
        } finally {
          isProgrammaticRelayoutRef.current = false;
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
    traces,
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
        <Text className="text-xs font-semibold text-indicator-info">
          Last sample:{" "}
          {new Date(latestDataTs).toLocaleTimeString("en-GB", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            timeZone: "UTC",
          })}{" "}
          UTC
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
        <EmptyState message="Providers detected, but no VRAM samples available yet." />
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
      <div ref={plotRef} style={{ width: "100%", minHeight: 300 }} />
    </View>
  );
}
