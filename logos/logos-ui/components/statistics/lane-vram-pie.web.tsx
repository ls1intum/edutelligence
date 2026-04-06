/**
 * Lane-aware VRAM pie chart (web-only).
 *
 * Shows one slice per lane colored by runtime_state,
 * plus an "Other used" slice for unattributed usage and a "Free" slice.
 * Delegates to the existing PlotlyPieChart so CDN loading, dark mode,
 * and legend handling are not duplicated.
 */

import React, { useMemo } from "react";

import PlotlyPieChart from "@/components/statistics/plotly-pie-chart";
import { getLaneStateColor } from "@/components/statistics/constants";
import type { LaneSignalData } from "@/components/statistics/types";

type LaneVramPieProps = {
  width: number;
  /** Per-lane signal data for the selected provider */
  lanes: Record<string, LaneSignalData>;
  /** Total VRAM of the selected provider in MB */
  totalVramMb: number;
  /** Free VRAM in MB */
  freeVramMb: number;
};

export default function LaneVramPie({
  width,
  lanes,
  totalVramMb,
  freeVramMb,
}: LaneVramPieProps) {
  const { slices, freePct, totalGb } = useMemo(() => {
    const result: Array<{ value: number; color: string; text: string }> = [];
    let allocatedMb = 0;

    // Sort lanes: running → loaded → sleeping → starting → cold → stopped → error
    const stateOrder: Record<string, number> = {
      running: 0, loaded: 1, sleeping: 2, starting: 3, cold: 4, stopped: 5, error: 6,
    };
    const sortedLanes = Object.entries(lanes).sort(([, a], [, b]) => {
      const ao = stateOrder[a.runtime_state] ?? 99;
      const bo = stateOrder[b.runtime_state] ?? 99;
      if (ao !== bo) return ao - bo;
      return a.model.localeCompare(b.model);
    });

    for (const [, lane] of sortedLanes) {
      const vramMb = lane.effective_vram_mb ?? 0;
      if (vramMb <= 0) continue;
      allocatedMb += vramMb;
      // Shorten model name to last path segment for legend readability
      const shortModel = lane.model.includes("/")
        ? lane.model.split("/").pop()!
        : lane.model;
      result.push({
        value: Number((vramMb / 1024).toFixed(3)),
        color: getLaneStateColor(lane.runtime_state),
        text: `${shortModel} [${lane.runtime_state}]`,
      });
    }

    const usedMb = totalVramMb - freeVramMb;
    const otherUsedMb = Math.max(usedMb - allocatedMb, 0);
    if (otherUsedMb > 0) {
      result.push({
        value: Number((otherUsedMb / 1024).toFixed(3)),
        color: "#1E3A8A",
        text: "Other used",
      });
    }

    if (freeVramMb > 0) {
      result.push({
        value: Number((freeVramMb / 1024).toFixed(3)),
        color: "#06FFA5",
        text: "Free",
      });
    }

    const totalGb = totalVramMb / 1024;
    const freePct = totalVramMb > 0 ? Math.round((freeVramMb / totalVramMb) * 100) : 0;
    return { slices: result.filter((s) => s.value > 0), freePct, totalGb };
  }, [lanes, totalVramMb, freeVramMb]);

  if (!slices.length) {
    return null;
  }

  return (
    <PlotlyPieChart
      data={slices}
      width={width}
      height={320}
      pieScale={0.85}
      legendPosition="bottom"
      hoverValueSuffix=" GB"
      hoverValueDecimals={2}
      centerText={{
        top: "Free",
        middle: `${freePct}%`,
        bottom: `of ${totalGb.toFixed(1)} GB`,
      }}
    />
  );
}
