import React from "react";

/**
 * Native fallback – on non-web platforms the Plotly pie chart is never
 * rendered because the calling code gates on `usePlotlyWeb`.
 * This stub exists so Metro's resolver finds a matching module.
 */

type PieSlice = {
  value: number;
  color: string;
  text: string;
};

type PlotlyPieChartProps = {
  data: PieSlice[];
  width: number;
  height?: number;
  centerText?: {
    top?: string;
    middle?: string;
    bottom?: string;
  };
  holeSize?: number;
  legendPosition?: "bottom" | "right";
};

export default function PlotlyPieChart(_props: PlotlyPieChartProps) {
  // Native should not reach this component – PieChart from gifted-charts is used instead.
  return null;
}
