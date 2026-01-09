import type { RequestEventStats } from "@/components/statistics/types";

export const formatRangeLabel = (range: { start: Date; end: Date }) => {
  const format = (d: Date) =>
    `${(d.getMonth() + 1).toString().padStart(2, "0")}/${d
      .getDate()
      .toString()
      .padStart(2, "0")}`;
  return `${format(range.start)} → ${format(range.end)}`;
};

export const applyTimeSeriesLabels = (
  series: RequestEventStats["timeSeries"],
  rangeStart: Date,
  rangeEnd: Date
): RequestEventStats["timeSeries"] => {
  if (!series.length) return [];

  const durationMs = Math.max(rangeEnd.getTime() - rangeStart.getTime(), 0);
  const labelStep = Math.max(1, Math.ceil(series.length / 5)); // halve the label count
  let lastLabel = "";

  return series.map((pt, idx) => {
    const next = { ...pt };
    if (idx % labelStep === 0) {
      const date = new Date(pt.timestamp);
      let newLabel = "";
      if (durationMs < 24 * 3600 * 1000) {
        newLabel = date.toLocaleTimeString("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        });
      } else if (durationMs < 7 * 24 * 3600 * 1000) {
        newLabel =
          date.toLocaleDateString("en-US", { month: "short", day: "numeric" }) +
          ` ${date.getHours()}h`;
      } else {
        newLabel = date.toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
        });
      }
      if (newLabel !== lastLabel) {
        next.label = newLabel;
        lastLabel = newLabel;
      }
    }
    return next;
  });
};

export const calculateDateRange = (
  period: string,
  customRange?: { start: Date; end: Date } | null
): { startDate: Date; endDate: Date } => {
  const endDate = new Date();
  let startDate = new Date();

  if (period === "custom" && customRange) {
    return { startDate: customRange.start, endDate: customRange.end };
  }

  switch (period) {
    case "24h":
      startDate.setHours(startDate.getHours() - 24);
      break;
    case "7d":
      startDate.setDate(startDate.getDate() - 7);
      break;
    case "30d":
      startDate.setDate(startDate.getDate() - 30);
      break;
  }

  return { startDate, endDate };
};
