import React from "react";

import VramChart from "@/components/statistics/vram-chart";

type PlotlyVramChartProps = {
  width: number;
  vramDayOffset: number;
  setVramDayOffset: (offset: number) => void;
  fetchVramStats: (options?: { silent?: boolean }) => void;
  isVramLoading: boolean;
  vramError: string | null;
  vramDataByProvider: { [url: string]: Array<any> };
  vramBaseline: any[];
  vramBucketSizeSec: number;
  vramTotalBuckets: number;
  getProviderColor: (index: number) => string;
  nowMs: number;
};

export default function PlotlyVramChart(props: PlotlyVramChartProps) {
  return <VramChart {...props} />;
}
