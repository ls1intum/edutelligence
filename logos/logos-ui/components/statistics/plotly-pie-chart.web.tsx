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
};

export default function PlotlyPieChart({
  data,
  width,
  height = 250,
  pieScale = 1,
  centerText,
  holeSize = 0.55,
  legendPosition = "bottom",
}: PlotlyPieChartProps) {
  const plotRef = useRef<HTMLDivElement | null>(null);
  const plotlyRef = useRef<any>(null);
  const initializedRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const isDark = useDarkMode();

  /* ── load Plotly from CDN ────────────────────────────────── */
  useEffect(() => {
    let cancelled = false;
    loadPlotly()
      .then((plotly) => {
        if (cancelled) return;
        plotlyRef.current = plotly;
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
    if (!plotRef.current || !plotlyRef.current || !data.length) return;

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

    // When legend is on the right, the pie sits on the left side.
    // Apply optional scale around domain center to shrink the donut.
    const baseDomain: { x: [number, number]; y: [number, number] } | undefined =
      isRight
        ? { x: [0, 0.55], y: [0, 1] }
        : clampedPieScale < 0.999
          ? { x: [0, 1], y: [0, 1] }
          : undefined;

    const pieDomain = baseDomain
      ? {
          x: scaleDomainAxis(baseDomain.x, clampedPieScale),
          y: scaleDomainAxis(baseDomain.y, clampedPieScale),
        }
      : undefined;

    // Annotation positions: center of pie domain
    const annX = pieDomain ? (pieDomain.x[0] + pieDomain.x[1]) / 2 : isRight ? 0.275 : 0.5;

    const trace: Record<string, any> = {
      type: "pie",
      values: data.map((d) => d.value),
      labels: data.map((d) => d.text),
      marker: {
        colors: data.map((d) => d.color),
        line: { color: "rgba(255,255,255,0.6)", width: 1.5 },
      },
      hole: holeSize,
      textinfo: "percent",
      textposition: "inside",
      textfont: { color: "#fff", size: 11 },
      hovertemplate:
        "<b>%{label}</b><br>%{value:.0f} requests · %{percent}<extra></extra>",
      hoverlabel: {
        font: {
          color: "#FFFFFF",
          size: 13,
        },
        namelength: -1,
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
          y: 0.57,
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
          y: 0.5,
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
          y: 0.43,
          xref: "paper",
          yref: "paper",
          xanchor: "center",
          yanchor: "middle",
        });
      }
    }

    // Sizing: use full width for right-legend layout, capped for bottom-legend
    const chartWidth = isRight ? width : Math.min(width, 280);
    const chartHeight = isRight ? Math.max(height, 260) : Math.min(height, Math.min(width, 280)) + 40;

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
          orientation: "h" as const,
          x: 0.5,
          xanchor: "center" as const,
          y: -0.05,
          font: { size: 11, color: legendColor },
          itemclick: false,
          itemdoubleclick: false,
        };

    const layout = {
      width: chartWidth,
      height: chartHeight,
      margin: isRight ? { l: 8, r: 8, t: 8, b: 8 } : { l: 8, r: 8, t: 8, b: 40 },
      paper_bgcolor: "rgba(0,0,0,0)",
      showlegend: true,
      legend,
      annotations,
    };

    const config = {
      responsive: true,
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
  }, [data, width, height, pieScale, centerText, holeSize, legendPosition, isDark]);

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
  const minH = isRight ? Math.max(height, 260) : Math.min(height, Math.min(width, 280));

  return (
    <View style={{ alignItems: "center" }}>
      <div
        ref={plotRef}
        style={{ minHeight: minH }}
      />
    </View>
  );
}
