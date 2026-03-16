import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { View } from "react-native";

import EmptyState from "@/components/statistics/empty-state";
import { loadPlotly } from "@/components/statistics/plotly-loader.web";
import SegmentedSwitch from "@/components/statistics/segmented-switch";
import { useDarkMode } from "@/components/statistics/use-dark-mode";

type ModelBreakdownItem = {
  modelId: number;
  modelName: string;
  providerName: string;
  requestCount: number;
};

type PlotlyRequestVolumeChartProps = {
  width: number;
  totalLineData: any[];
  cloudLineData: any[];
  localLineData: any[];
  /** Per-model time-series keyed by model name, each array mirrors totalLineData indices */
  modelSeriesMap?: Record<string, any[]>;
  modelBreakdown?: ModelBreakdownItem[];
  /** Called when the user zooms in/out. `null` means reset to full view. Display-only — should NOT trigger data re-fetch. */
  onZoom?: (range: { start: Date; end: Date } | null) => void;
  /** Bump this number to programmatically reset the chart zoom to full range. */
  resetZoomTrigger?: number;
  colors: { total: string; cloud: string; local: string };
  modelColors?: Record<string, string>;
};

const MIN_BAR_WIDTH_MS = 30_000;

const MODEL_PALETTE = [
  "#F29C6E", // orange
  "#3BE9DE", // cyan
  "#9D4EDD", // purple
  "#06FFA5", // green
  "#F59E0B", // amber
  "#EC4899", // pink
  "#6366F1", // indigo
  "#14B8A6", // teal
];

const BUCKET_RANGE_DATE_FMT = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
});

const BUCKET_RANGE_TIME_FMT = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

type StackableBarTrace = {
  x?: unknown[];
  y?: unknown[];
};

function inferBarWidthMs(points: any[]): number {
  if (points.length < 2) return 60 * 60 * 1000;

  let minDiff = Number.POSITIVE_INFINITY;
  for (let i = 1; i < points.length; i += 1) {
    const prevTs = Number(points[i - 1]?.timestamp);
    const currTs = Number(points[i]?.timestamp);
    if (!Number.isFinite(prevTs) || !Number.isFinite(currTs)) continue;
    const diff = currTs - prevTs;
    if (diff > 0 && diff < minDiff) minDiff = diff;
  }

  if (!Number.isFinite(minDiff)) return 60 * 60 * 1000;
  return Math.max(Math.floor(minDiff * 0.82), MIN_BAR_WIDTH_MS);
}

function toTimestampMs(raw: any): number {
  const numeric = Number(raw?.timestamp);
  if (Number.isFinite(numeric)) return numeric;
  const parsed = new Date(raw?.timestamp || "").getTime();
  if (Number.isFinite(parsed)) return parsed;
  return Date.now();
}

function formatBucketRangeLabel(startMs: number, spanMs: number): string {
  const start = new Date(startMs);
  const end = new Date(startMs + spanMs);
  const sameDay =
    start.getFullYear() === end.getFullYear() &&
    start.getMonth() === end.getMonth() &&
    start.getDate() === end.getDate();

  if (sameDay) {
    return `${BUCKET_RANGE_DATE_FMT.format(start)} ${BUCKET_RANGE_TIME_FMT.format(start)} - ${BUCKET_RANGE_TIME_FMT.format(end)}`;
  }
  return `${BUCKET_RANGE_DATE_FMT.format(start)} ${BUCKET_RANGE_TIME_FMT.format(start)} - ${BUCKET_RANGE_DATE_FMT.format(end)} ${BUCKET_RANGE_TIME_FMT.format(end)}`;
}

function inferBucketSpanMsFromHoverPoint(point: any): number {
  const parseTs = (value: any): number => {
    const ts = new Date(value).getTime();
    return Number.isFinite(ts) ? ts : NaN;
  };

  const xValues = Array.isArray(point?.fullData?.x) ? point.fullData.x : [];
  const pointIndex = Number(point?.pointNumber);
  const currentTs = parseTs(point?.x);
  if (!Number.isFinite(currentTs)) return 60 * 1000;

  const candidates: number[] = [];
  if (Number.isInteger(pointIndex)) {
    if (pointIndex > 0) {
      const prevTs = parseTs(xValues[pointIndex - 1]);
      if (Number.isFinite(prevTs) && currentTs > prevTs) {
        candidates.push(currentTs - prevTs);
      }
    }
    if (pointIndex < xValues.length - 1) {
      const nextTs = parseTs(xValues[pointIndex + 1]);
      if (Number.isFinite(nextTs) && nextTs > currentTs) {
        candidates.push(nextTs - currentTs);
      }
    }
  }

  if (!candidates.length) {
    for (let i = 1; i < xValues.length; i += 1) {
      const prevTs = parseTs(xValues[i - 1]);
      const nextTs = parseTs(xValues[i]);
      if (!Number.isFinite(prevTs) || !Number.isFinite(nextTs)) continue;
      const diff = nextTs - prevTs;
      if (diff > 0) candidates.push(diff);
    }
  }

  if (!candidates.length) return 60 * 1000;
  return Math.max(Math.min(...candidates), 60 * 1000);
}

function toStackBucketKey(rawX: unknown, index: number): string {
  if (rawX instanceof Date) {
    const ts = rawX.getTime();
    if (Number.isFinite(ts)) return `t:${ts}`;
  }

  if (typeof rawX === "number" && Number.isFinite(rawX)) {
    return `n:${rawX}`;
  }

  if (typeof rawX === "string") {
    const ts = new Date(rawX).getTime();
    if (Number.isFinite(ts)) return `t:${ts}`;
    return `s:${rawX}`;
  }

  return `i:${index}`;
}

function computeStackedMaxY(traces: StackableBarTrace[]): number {
  const stackedByBucket = new Map<string, number>();
  let maxStacked = 0;

  for (const trace of traces) {
    const xValues = Array.isArray(trace.x) ? trace.x : [];
    const yValues = Array.isArray(trace.y) ? trace.y : [];

    for (let i = 0; i < yValues.length; i += 1) {
      const value = Number(yValues[i]);
      if (!Number.isFinite(value) || value <= 0) continue;

      const bucketKey = toStackBucketKey(xValues[i], i);
      const next = (stackedByBucket.get(bucketKey) || 0) + value;
      stackedByBucket.set(bucketKey, next);
      if (next > maxStacked) maxStacked = next;
    }
  }

  return maxStacked;
}

type ViewMode = "provider" | "model";

export default function PlotlyRequestVolumeChart({
  width,
  totalLineData,
  cloudLineData,
  localLineData,
  modelSeriesMap,
  modelBreakdown,
  onZoom,
  resetZoomTrigger,
  colors,
  modelColors,
}: PlotlyRequestVolumeChartProps) {
  const plotRef = useRef<HTMLDivElement | null>(null);
  const plotlyRef = useRef<any>(null);
  const initializedRef = useRef(false);
  const relayoutHandlerRef = useRef<any>(null);
  const isProgrammaticRef = useRef(false);
  const pendingResetRef = useRef(false);
  // uirevision counter — bumped only when the chart should auto-range (e.g. reset or view-mode switch).
  // Keeping it stable across incremental data pushes preserves the user's current viewport.
  const uiRevisionRef = useRef(1);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const onZoomRef = useRef(onZoom);
  onZoomRef.current = onZoom;
  const hoverHandlerRef = useRef<any>(null);
  const unhoverHandlerRef = useRef<any>(null);
  const [plotlyError, setPlotlyError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("provider");
  const [hoverTooltip, setHoverTooltip] = useState<{
    visible: boolean;
    left: number;
    top: number;
    title: string;
    items: { name: string; value: number; color: string }[];
  }>({
    visible: false,
    left: 0,
    top: 0,
    title: "",
    items: [],
  });
  const isDark = useDarkMode();

  const chartHeight = 300;

  // ── Sorted model names (by request count desc) ──────────────────────
  const sortedModelNames = useMemo(() => {
    if (!modelBreakdown?.length) return [];
    return [...modelBreakdown]
      .sort((a, b) => b.requestCount - a.requestCount)
      .map((m) => m.modelName);
  }, [modelBreakdown]);

  const resolvedModelColors = useMemo(() => {
    const map: Record<string, string> = { ...(modelColors || {}) };
    sortedModelNames.forEach((name, idx) => {
      if (!map[name]) {
        map[name] = MODEL_PALETTE[idx % MODEL_PALETTE.length];
      }
    });
    return map;
  }, [modelColors, sortedModelNames]);

  // ── Traces ──────────────────────────────────────────────────────────
  const providerTraces = useMemo(() => {
    const barWidthMs = inferBarWidthMs(totalLineData);
    const mkTrace = (name: string, color: string, points: any[]) => ({
      type: "bar",
      name,
      x: points.map((p: any) => new Date(toTimestampMs(p))),
      y: points.map((p: any) => Number(p.value || 0)),
      width: points.map(() => barWidthMs),
      marker: { color },
      // Keep Plotly hover events/spikes, but render our own tooltip content.
      hoverinfo: "none",
    });
    return [
      mkTrace("Cloud", colors.cloud, cloudLineData),
      mkTrace("Local", colors.local, localLineData),
    ];
  }, [totalLineData, cloudLineData, localLineData, colors]);

  const modelTraces = useMemo(() => {
    if (!modelSeriesMap || !sortedModelNames.length) return [];
    const barWidthMs = inferBarWidthMs(totalLineData);
    return sortedModelNames.map((name) => {
      const points = modelSeriesMap[name] || [];
      return {
        type: "bar",
        name,
        x: points.map((p: any) => new Date(toTimestampMs(p))),
        y: points.map((p: any) => Number(p.value || 0)),
        width: points.map(() => barWidthMs),
        marker: { color: resolvedModelColors[name] || "#94A3B8" },
        // Keep Plotly hover events/spikes, but render our own tooltip content.
        hoverinfo: "none",
      };
    });
  }, [modelSeriesMap, sortedModelNames, resolvedModelColors, totalLineData]);

  const traces = viewMode === "model" && modelTraces.length > 0 ? modelTraces : providerTraces;


  // ── Load Plotly ─────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    loadPlotly()
      .then((plotly) => {
        if (cancelled) return;
        plotlyRef.current = plotly;
      })
      .catch((err) => {
        if (cancelled) return;
        setPlotlyError(err instanceof Error ? err.message : "Failed to load Plotly.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Build layout ────────────────────────────────────────────────────
  const buildLayout = useCallback(() => {
    const textMuted = isDark ? "#94A3B8" : "#64748B";
    const gridColor = isDark ? "#334155" : "#CBD5E1";
    const zeroLine = isDark ? "#475569" : "#94A3B8";
    const plotBg = isDark ? "rgba(30,41,59,0.5)" : "rgba(15,23,42,0.06)";
    const legendColor = isDark ? "#CBD5E1" : "#1E293B";

    return {
      width,
      height: chartHeight,
      margin: { l: 48, r: 16, t: 20, b: 64 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: plotBg,
      dragmode: "zoom",
      uirevision: uiRevisionRef.current,
      hovermode: "x unified",
      barmode: "stack",
      bargap: 0.18,
      xaxis: {
        type: "date",
        fixedrange: false,
        showgrid: true,
        gridcolor: gridColor,
        showspikes: true,
        spikemode: "across",
        spikesnap: "cursor",
        spikecolor: isDark ? "#94A3B8" : "#64748B",
        spikethickness: 1.25,
        tickfont: { color: textMuted, size: 11 },
        title: { text: "Time", font: { color: textMuted, size: 11 }, standoff: 12 },
      },
      yaxis: {
        fixedrange: true,
        showgrid: true,
        gridcolor: gridColor,
        zerolinecolor: zeroLine,
        tickfont: { color: textMuted, size: 11 },
        title: { text: "Requests", font: { color: textMuted, size: 11 } },
        rangemode: "nonnegative",
        range: [0, undefined as number | undefined],
      },
      legend: {
        orientation: "h",
        x: 0,
        y: 1.16,
        traceorder: "normal",
        font: { color: legendColor },
      },
      hoverlabel: {
        bgcolor: isDark ? "#1E293B" : "#FFFFFF",
        font: {
          color: isDark ? "#F1F5F9" : "#1E293B",
          size: 13,
        },
        namelength: -1,
      },
    };
  }, [width, chartHeight, isDark]);

  const config = useMemo(() => ({
    responsive: true,
    displaylogo: false,
    displayModeBar: false,
    scrollZoom: false,
    doubleClick: false,
  }), []);

  // ── Render / update the plot ────────────────────────────────────────
  useEffect(() => {
    let disposed = false;

    const renderPlot = async () => {
      if (!plotRef.current || !plotlyRef.current || !traces.length || !totalLineData.length) {
        return;
      }

      const plotly = plotlyRef.current;
      const graphDiv = plotRef.current;
      const layout = buildLayout();

      // In stacked mode, y-max must use the sum of traces per x-bucket.
      const maxVisible = computeStackedMaxY(traces);
      // At least show y up to 1 so the grid is visible even with 0 requests
      layout.yaxis.range = [0, Math.max(maxVisible * 1.15, 1)];

      if (!initializedRef.current) {
        isProgrammaticRef.current = true;
        try {
          await plotly.newPlot(graphDiv, traces, layout, config);
        } finally {
          isProgrammaticRef.current = false;
        }

        // Report zoom/reset to parent
        relayoutHandlerRef.current = (ev: Record<string, any>) => {
          if (isProgrammaticRef.current) return;
          if (ev["xaxis.autorange"]) {
            onZoomRef.current?.(null);
            return;
          }
          const start = ev["xaxis.range[0]"];
          const end = ev["xaxis.range[1]"];
          if (start && end) {
            onZoomRef.current?.({ start: new Date(start), end: new Date(end) });
          }
        };
        (graphDiv as any).on("plotly_relayout", relayoutHandlerRef.current);

        hoverHandlerRef.current = (ev: any) => {
          const points = Array.isArray(ev?.points) ? ev.points : [];
          if (!points.length) {
            setHoverTooltip((prev) =>
              prev.visible ? { ...prev, visible: false } : prev
            );
            return;
          }

          const xMs = new Date(points[0]?.x).getTime();
          if (!Number.isFinite(xMs)) return;
          const spanMs = inferBucketSpanMsFromHoverPoint(points[0]);

          const containerRect = containerRef.current?.getBoundingClientRect();
          const nativeEvent = ev?.event;
          const clientX = Number(nativeEvent?.clientX);
          const clientY = Number(nativeEvent?.clientY);
          if (!containerRect || !Number.isFinite(clientX) || !Number.isFinite(clientY)) {
            return;
          }

          const items = points.map((pt: any) => {
            const markerColor = pt?.fullData?.marker?.color;
            const color = Array.isArray(markerColor)
              ? markerColor[pt.pointNumber]
              : markerColor;
            return {
              name: String(pt?.fullData?.name || ""),
              value: Number(pt?.y || 0),
              color: typeof color === "string" ? color : "#64748B",
            };
          });

          const title = formatBucketRangeLabel(xMs, spanMs);
          const longestLineChars = Math.max(
            title.length,
            ...items.map((item) => `${item.name} : ${Math.round(item.value)} requests`.length)
          );
          const estimatedHeight = 34 + items.length * 24;
          const estimatedWidth = Math.max(180, Math.min(460, longestLineChars * 7 + 28));
          let left = clientX - containerRect.left + 14;
          let top = clientY - containerRect.top + 14;
          if (left + estimatedWidth > containerRect.width - 8) {
            left = clientX - containerRect.left - estimatedWidth - 14;
          }
          if (top + estimatedHeight > containerRect.height - 8) {
            top = clientY - containerRect.top - estimatedHeight - 14;
          }

          setHoverTooltip({
            visible: true,
            left: Math.max(8, left),
            top: Math.max(8, top),
            title,
            items,
          });
        };
        unhoverHandlerRef.current = () => {
          setHoverTooltip((prev) =>
            prev.visible ? { ...prev, visible: false } : prev
          );
        };
        (graphDiv as any).on("plotly_hover", hoverHandlerRef.current);
        (graphDiv as any).on("plotly_unhover", unhoverHandlerRef.current);
        initializedRef.current = true;
      } else {
        // If a reset was requested, bump uirevision so Plotly auto-ranges to the new full data
        if (pendingResetRef.current) {
          uiRevisionRef.current += 1;
          layout.uirevision = uiRevisionRef.current;
          layout.xaxis = { ...layout.xaxis, autorange: true } as any;
          pendingResetRef.current = false;
        }
        isProgrammaticRef.current = true;
        try {
          await plotly.react(graphDiv, traces, layout, config);
        } finally {
          isProgrammaticRef.current = false;
        }
      }

      if (disposed) return;
    };

    renderPlot().catch((err) => {
      if (disposed) return;
      setPlotlyError(err instanceof Error ? err.message : "Failed to render Plotly chart.");
    });

    return () => {
      disposed = true;
    };
  }, [width, chartHeight, traces, totalLineData, buildLayout, config]);

  // ── Cleanup ─────────────────────────────────────────────────────────
  useEffect(() => {
    const graphDiv = plotRef.current;
    return () => {
      if (!graphDiv || !plotlyRef.current) return;
      try {
        if (relayoutHandlerRef.current) {
          (graphDiv as any).removeListener("plotly_relayout", relayoutHandlerRef.current);
        }
        if (hoverHandlerRef.current) {
          (graphDiv as any).removeListener("plotly_hover", hoverHandlerRef.current);
        }
        if (unhoverHandlerRef.current) {
          (graphDiv as any).removeListener("plotly_unhover", unhoverHandlerRef.current);
        }
        plotlyRef.current.purge(graphDiv);
      } catch {
        // no-op cleanup
      }
    };
  }, []);

  // ── Reset zoom when parent requests it ──────────────────────────────
  useEffect(() => {
    if (resetZoomTrigger == null) return;
    // Mark a pending reset so the next render effect auto-ranges
    pendingResetRef.current = true;
    // Also try to autorange immediately in case data hasn't changed
    if (plotRef.current && plotlyRef.current && initializedRef.current) {
      isProgrammaticRef.current = true;
      plotlyRef.current
        .relayout(plotRef.current, { "xaxis.autorange": true })
        .finally(() => { isProgrammaticRef.current = false; });
    }
  }, [resetZoomTrigger]);

  // ── Render ──────────────────────────────────────────────────────────
  if (!totalLineData.length) {
    return <EmptyState message="No timeline data available." />;
  }

  if (plotlyError) {
    return <EmptyState message={plotlyError} />;
  }

  const hasModelData = modelTraces.length > 0;

  return (
    <View>
      {/* View mode selector */}
      {hasModelData && (
        <View className="mb-2.5">
          <SegmentedSwitch
            value={viewMode}
            onChange={(mode) => {
              setViewMode(mode as ViewMode);
              // Bump uirevision so Plotly auto-ranges after trace swap
              uiRevisionRef.current += 1;
              // Force full re-init so Plotly redraws traces + legend correctly
              initializedRef.current = false;
            }}
            options={[
              { value: "provider", label: "Cloud / Local" },
              { value: "model", label: "By Model" },
            ]}
          />
        </View>
      )}

      <div ref={containerRef} style={{ position: "relative", width: "100%" }}>
        <div ref={plotRef} style={{ width: "100%", minHeight: chartHeight }} />
        {hoverTooltip.visible && (
          <div
            style={{
              position: "absolute",
              left: hoverTooltip.left,
              top: hoverTooltip.top,
              pointerEvents: "none",
              zIndex: 30,
              maxWidth: 460,
              border: `1px solid ${isDark ? "#475569" : "#334155"}`,
              background: isDark ? "rgba(15,23,42,0.96)" : "rgba(255,255,255,0.97)",
              color: isDark ? "#F8FAFC" : "#1E293B",
              borderRadius: 0,
              boxShadow: "none",
              padding: "8px 10px",
            }}
          >
            <div
              style={{
                fontSize: 13,
                lineHeight: "18px",
                fontWeight: 400,
                marginBottom: 4,
              }}
            >
              {hoverTooltip.title}
            </div>
            {hoverTooltip.items.map((item, idx) => (
              <div
                key={`${item.name}-${idx}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  fontSize: 13,
                  lineHeight: "18px",
                }}
              >
                <div
                  style={{
                    width: 12,
                    height: 12,
                    backgroundColor: item.color,
                    borderRadius: 0,
                    flexShrink: 0,
                  }}
                />
                <div>
                  {item.name} : {Math.round(item.value)} requests
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </View>
  );
}
