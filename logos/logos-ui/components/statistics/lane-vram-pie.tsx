import React from "react";

import type { LaneSignalData } from "@/components/statistics/types";

/**
 * Native fallback – on non-web platforms the lane VRAM pie is never
 * rendered because the calling code gates on `usePlotlyWeb`.
 * This stub exists so Metro's resolver finds a matching module.
 */

type LaneVramPieProps = {
  width: number;
  lanes: Record<string, LaneSignalData>;
  totalVramMb: number;
  freeVramMb: number;
};

export default function LaneVramPie(_props: LaneVramPieProps) {
  return null;
}
