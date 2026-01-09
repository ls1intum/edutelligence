import { Platform } from "react-native";
import { buildMockRows, MAX_MOCK_ROWS } from "@/lib/utils/mockData";
import type { RequestEventResponse } from "./types";

export const MOCK_RESPONSE: RequestEventResponse = {
  rows: buildMockRows(MAX_MOCK_ROWS, 30), // 30 days
};

export const API_BASE =
  Platform.OS === "web"
    ? ""
    : process.env.EXPO_PUBLIC_API_BASE || "http://localhost:8080";

export const CHART_PALETTE = {
  total: "#1E3A8A", // Dark Blue for cumulative total
  cloud: "#3BE9DE", // Cyan
  local: "#F29C6E", // Orange for local
  provider1: "#F59E0B", // Amber
  provider2: "#9D4EDD", // Purple
  provider3: "#06FFA5", // Green
  textLight: "#64748B", // Slate-500 (readable on light)
  textDark: "#94A3B8", // Slate-400 (readable on dark)
};

export const VRAM_HOUR_SPACING_PX = 91; // ~30% more horizontal breathing room

export const PROVIDER_COLORS = [
  CHART_PALETTE.provider1,
  CHART_PALETTE.cloud,
  CHART_PALETTE.local,
  CHART_PALETTE.provider2,
  CHART_PALETTE.provider3,
];

export const getProviderColor = (index: number): string => {
  return PROVIDER_COLORS[index % PROVIDER_COLORS.length];
};
