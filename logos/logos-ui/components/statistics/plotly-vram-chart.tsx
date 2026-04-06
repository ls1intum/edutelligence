import React from "react";

import VramChart from "@/components/statistics/vram-chart";
import type { LaneSignalData } from "@/components/statistics/types";

type PlotlyVramChartProps = {
  width: number;
  vramDayOffset: number;
  setVramDayOffset: (offset: number) => void;
  fetchVramStats: (options?: { silent?: boolean }) => void;
  isVramLoading: boolean;
  vramError: string | null;
  vramDataByProvider: { [url: string]: Array<any> };
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
  laneStateByProvider?: Record<string, Record<string, LaneSignalData>>;
};

export default function PlotlyVramChart({
  providerMetaByName: _meta,
  laneStateByProvider: _lanes,
  ...props
}: PlotlyVramChartProps) {
  // Native fallback passes through to VramChart, dropping web-only props
  return <VramChart {...props} />;
}
