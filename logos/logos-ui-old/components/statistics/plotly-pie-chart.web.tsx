import React, { useEffect, useRef, useState } from "react";
import { View } from "react-native";

import { loadPlotly } from "@/components/statistics/plotly-loader.web";
import { useDarkMode } from "@/components/statistics/use-dark-mode";

type PieSlice = {
  value: number;
  color: string;
  text: string;
};

type PlotlyPieChartProps = {
  data: PieSlice[];
  width: number;
  height?: number;
  /** Scales pie diameter (1 = default size). */
  pieScale?: number;
  centerText?: {
    top?: string;
    middle?: string;
    bottom?: string;
  };
  holeSize?: number;
  /** Where the legend is rendered. "bottom" is horizontal below, "right" is vertical beside the pie. */
  legendPosition?: "bottom" | "right";
  hoverValueSuffix?: string;
  hoverValueDecimals?: number;
};

export default function PlotlyPieChart({
  data,
  width,
  height = 250,
  pieScale = 1,
  centerText,
  holeSize = 0.55,
  legendPosition = "bottom",
  hoverValueSuffix = " requests",
  hoverValueDecimals = 0,
}: PlotlyPieChartProps) {
  const plotRef = useRef<HTMLDivElement | null>(null);
  const plotlyRef = useRef<any>(null);
  const initializedRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [plotlyReady, setPlotlyReady] = useState(false);
  const isDark = useDarkMode();

  /* ── load Plotly from CDN ────────────────────────────────── */
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
        setError(err instanceof Error ? err.message : "Failed to load Plotly.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /* ── render / update the pie chart ──────────────────────── */
  useEffect(() => {
    if (!plotlyReady || !plotRef.current || !plotlyRef.current || !data.length) return;

    const plotly = plotlyRef.current;
    const graphDiv = plotRef.current;

    const isRight = legendPosition === "right";

    // Dark mode colors
    const textMuted = isDark ? "#94A3B8" : "#64748B";
    const textStrong = isDark ? "#F1F5F9" : "#0F172A";
    const legendColor = isDark ? "#CBD5E1" : "#334155";

    const clampedPieScale = Math.max(0.5, Math.min(pieScale, 1));

    const scaleDomainAxis = (
      range: [number, number],
      scale: number,
    ): [number, number] => {
      const center = (range[0] + range[1]) / 2;
      const half = ((range[1] - range[0]) * scale) / 2;
      return [center - half, center + half];
    };

    // For right legend: pie on left half of the canvas, legend on the right.
    // For bottom legend: pie occupies the full plot area (no explicit domain
    // so Plotly inscribes the donut into whatever rectangle margins leave).
    const pieDomain: { x: [number, number]; y: [number, number] } | undefined =
      isRight
        ? {
            x: scaleDomainAxis([0, 0.55], clampedPieScale),
            y: scaleDomainAxis([0, 1], clampedPieScale),
          }
        : undefined;

    // Annotation positions: center of pie domain (or canvas center for bottom)
    const annX = pieDomain ? (pieDomain.x[0] + pieDomain.x[1]) / 2 : 0.5;
    const annY = pieDomain ? (pieDomain.y[0] + pieDomain.y[1]) / 2 : 0.5;

    const trace: Record<string, any> = {
      type: "pie",
      values: data.map((d) => d.value),
      labels: data.map((d) => d.text),
      marker: {
        colors: data.map((d) => d.color),
        line: { color: "rgba(255,255,255,0.6)", width: 1.5 },
      },
      hole: holeSize,
      textinfo: "none",
      textposition: "inside",
      textfont: { color: "#fff", size: 11 },
      hovertemplate:
        `<b>%{label}</b><br>%{value:.${hoverValueDecimals}f}${hoverValueSuffix} · %{percent}<extra></extra>`,
      // Explicit dark tooltip background so the slice color (which can be
      // light/pastel) doesn't bleed into the hover and make text invisible.
      // Borders are radius-rounded by Plotly automatically when we set
      // bordercolor; the colors below match the volume / VRAM custom hovers.
      hoverlabel: {
        bgcolor: isDark ? "rgba(15,23,42,0.96)" : "rgba(255,255,255,0.98)",
        bordercolor: isDark ? "rgba(148,163,184,0.25)" : "rgba(15,23,42,0.12)",
        font: {
          family: "system-ui,-apple-system,sans-serif",
          color: isDark ? "#F8FAFC" : "#0F172A",
          size: 13,
        },
        namelength: -1,
        align: "left",
      },
      sort: false,
      direction: "clockwise",
      rotation: 0,
      ...(pieDomain ? { domain: pieDomain } : {}),
    };

    const annotations: Record<string, any>[] = [];
    if (centerText) {
      if (centerText.top) {
        annotations.push({
          text: centerText.top,
          font: { size: 12, color: textMuted },
          showarrow: false,
          x: annX,
          y: annY + 0.07,
          xref: "paper",
          yref: "paper",
          xanchor: "center",
          yanchor: "middle",
        });
      }
      if (centerText.middle) {
        annotations.push({
          text: `<b>${centerText.middle}</b>`,
          font: { size: 20, color: textStrong },
          showarrow: false,
          x: annX,
          y: annY,
          xref: "paper",
          yref: "paper",
          xanchor: "center",
          yanchor: "middle",
        });
      }
      if (centerText.bottom) {
        annotations.push({
          text: centerText.bottom,
          font: { size: 11, color: textMuted },
          showarrow: false,
          x: annX,
          y: annY - 0.07,
          xref: "paper",
          yref: "paper",
          xanchor: "center",
          yanchor: "middle",
        });
      }
    }

    // Sizing: clamp to the card's available width so the canvas never
    // overflows ChartCard's `overflow-hidden` (which was clipping the
    // pie when the card was narrower than our previous 280 px floor).
    // `responsive: false` below keeps Plotly from re-fitting on its own.
    const chartWidth = isRight
      ? Math.max(220, Math.min(width, 360))
      : Math.max(220, Math.min(width, 320));
    // Slice count drives bottom margin: each legend row is ~18 px and the
    // legend sits in the bottom margin. We grow with every slice (no cap)
    // so long legends don't extend past the canvas and clip.
    const sliceCount = data.length;
    const bottomMarginForLegend = 24 + sliceCount * 18;
    // Reserve room above the donut for hover labels with long model names.
    // Without this Plotly draws the tooltip at y < 0 and ChartCard's
    // `overflow-hidden` clips it (and the pie behind it can look "cut off").
    const topMarginForHover = 56;
    const chartHeight = isRight
      ? Math.max(height, 240)
      : 220 + topMarginForHover + bottomMarginForLegend;

    const legend = isRight
      ? {
          orientation: "v" as const,
          x: 0.6,
          xanchor: "left" as const,
          y: 0.5,
          yanchor: "middle" as const,
          font: { size: 12, color: legendColor },
          itemclick: false,
          itemdoubleclick: false,
        }
      : {
          // Vertical legend below the donut. Plotly places the legend in
          // the bottom margin when y < 0; we size that margin precisely so
          // the donut keeps its full ~180 px diameter regardless of how
          // many slices the legend has.
          orientation: "v" as const,
          x: 0.5,
          xanchor: "center" as const,
          y: -0.05,
          yanchor: "top" as const,
          font: { size: 11, color: legendColor },
          itemclick: false,
          itemdoubleclick: false,
        };

    const layout = {
      width: chartWidth,
      height: chartHeight,
      margin: isRight
        ? { l: 8, r: 8, t: 8, b: 8 }
        : { l: 8, r: 8, t: topMarginForHover, b: bottomMarginForLegend },
      paper_bgcolor: "rgba(0,0,0,0)",
      showlegend: true,
      legend,
      annotations,
    };

    const config = {
      // Disable responsive auto-fit so our explicit chartWidth/chartHeight
      // is honoured. Without this, Plotly grows the donut to fill its div
      // and breaks the per-card consistency we're trying to enforce.
      responsive: false,
      displaylogo: false,
      displayModeBar: false,
      staticPlot: false,
    };

    if (!initializedRef.current) {
      plotly.newPlot(graphDiv, [trace], layout, config);
      initializedRef.current = true;
    } else {
      plotly.react(graphDiv, [trace], layout, config);
    }
  }, [
    data,
    width,
    height,
    pieScale,
    centerText,
    holeSize,
    legendPosition,
    isDark,
    plotlyReady,
    hoverValueDecimals,
    hoverValueSuffix,
  ]);

  /* ── cleanup on unmount ─────────────────────────────────── */
  useEffect(() => {
    const graphDiv = plotRef.current;
    return () => {
      if (!graphDiv || !plotlyRef.current) return;
      try {
        plotlyRef.current.purge(graphDiv);
        initializedRef.current = false;
      } catch {
        // no-op
      }
    };
  }, []);

  if (error || !data.length) return null;

  const isRight = legendPosition === "right";
  const targetW = isRight
    ? Math.max(220, Math.min(width, 360))
    : Math.max(220, Math.min(width, 320));
  const sliceCount = data.length;
  const bottomMarginForLegend = 24 + sliceCount * 18;
  const topMarginForHover = 56;
  const targetH = isRight
    ? Math.max(height, 240)
    : 220 + topMarginForHover + bottomMarginForLegend;

  return (
    <View style={{ alignItems: "center" }}>
      <div
        ref={plotRef}
        style={{ width: targetW, height: targetH }}
      />
    </View>
  );
}
