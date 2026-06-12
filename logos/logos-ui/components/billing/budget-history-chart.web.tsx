import React, { useEffect, useRef, useState } from "react";
import { Text } from "@/components/ui/text";
import { loadPlotly } from "@/components/statistics/plotly-loader.web";

export type BudgetBucket = {
  seriesKey: string;
  bucketTs: number;
  costMicroCents: number;
};

type Props = {
  data: BudgetBucket[];
  title?: string;
  height?: number;
  xAxisFormat?: string;
  rangeStart?: number;
  rangeEnd?: number;
  barWidthMs?: number;
};

const PALETTE = [
  "#F29C6E",
  "#3BE9DE",
  "#9D4EDD",
  "#06FFA5",
  "#EC4899",
  "#6366F1",
  "#F59E0B",
  "#14B8A6",
];

function microCentsToUsd(mc: number): number {
  return mc / 100_000_000;
}

function paletteIndexForKey(key: string): number {
  let sum = 0;

  for (const char of key) {
    sum += char.charCodeAt(0);
  }

  return sum % PALETTE.length;
}

export default function BudgetHistoryChart({
  data,
  title,
  height = 320,
  xAxisFormat = "%b %d",
  rangeStart,
  rangeEnd,
  barWidthMs,
}: Props) {
  const containerRef = useRef<any>(null);
  const [plotlyReady, setPlotlyReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadPlotly()
      .then(() => setPlotlyReady(true))
      .catch(() => setError("Failed to load chart library"));
  }, []);

  useEffect(() => {
    if (!plotlyReady || !containerRef.current) return;

    const Plotly = (window as any).Plotly;
    if (!Plotly) return;

    const seriesMap = new Map<string, Map<number, number>>();
    for (const bucket of data) {
      if (!seriesMap.has(bucket.seriesKey)) {
        seriesMap.set(bucket.seriesKey, new Map());
      }
      seriesMap
        .get(bucket.seriesKey)!
        .set(bucket.bucketTs, microCentsToUsd(bucket.costMicroCents));
    }

    const allTimestamps = [...new Set(data.map((b) => b.bucketTs))].sort(
      (a, b) => a - b
    );
    const xDates = allTimestamps.map((ts) => new Date(ts));

    const traces = Array.from(seriesMap.entries())
      .filter(([, tsMap]) => Array.from(tsMap.values()).some((v) => v > 0))
      .map(([key, tsMap]) => ({
        type: "bar",
        name: key,
        x: xDates,
        y: allTimestamps.map((ts) => tsMap.get(ts) ?? 0),
        marker: { color: PALETTE[paletteIndexForKey(key)] },
        hovertemplate: `%{y:.6f} USD<br>${key}<extra></extra>`,
        ...(barWidthMs != null ? { width: barWidthMs } : {}),
      }));

    const xRange =
      rangeStart != null && rangeEnd != null
        ? [new Date(rangeStart), new Date(rangeEnd)]
        : undefined;

    const layout = {
      barmode: "stack",
      bargap: 0,
      title: title ? { text: title, font: { size: 14 } } : undefined,
      height,
      margin: { t: title ? 40 : 16, r: 16, b: 60, l: 70 },
      xaxis: { type: "date", tickformat: xAxisFormat, range: xRange },
      yaxis: { title: "USD", tickformat: ".4f" },
      showlegend: true,
      legend: { orientation: "h", y: -0.2 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      dragmode: false,
    };

    Plotly.react(containerRef.current, traces, layout, {
      responsive: true,
      displayModeBar: false,
      scrollZoom: false,
    });
  }, [plotlyReady, data, title, height, xAxisFormat, rangeStart, rangeEnd]);

  if (error) {
    return <Text style={{ color: "#EF4444" }}>{error}</Text>;
  }

  return <div ref={containerRef} style={{ width: "100%", height }} />;
}
