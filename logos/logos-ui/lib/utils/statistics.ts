import type { RequestEventStats } from "@/components/statistics/types";

export function formatRangeLabel(range: { start: Date; end: Date }) {
  const dayMs = 24 * 60 * 60 * 1000;
  const hourMs = 60 * 60 * 1000;
  const threeDaysMs = 3 * dayMs;
  const durationMs = Math.max(range.end.getTime() - range.start.getTime(), 0);

  const formatDay = (d: Date) =>
    `${d.getDate().toString().padStart(2, "0")}/${(d.getMonth() + 1)
      .toString()
      .padStart(2, "0")}`;

  const formatTime = (
    d: Date,
    opts: { withMinutes: boolean; withSeconds: boolean }
  ) => {
    const hours = d.getHours();
    const hours12 = hours % 12 || 12;
    const meridiem = hours >= 12 ? "pm" : "am";
    const minutes = d.getMinutes().toString().padStart(2, "0");
    const seconds = d.getSeconds().toString().padStart(2, "0");

    if (!opts.withMinutes) {
      return `${hours12} ${meridiem}`;
    }

    if (!opts.withSeconds) {
      return `${hours12}:${minutes} ${meridiem}`;
    }

    return `${hours12}:${minutes}:${seconds} ${meridiem}`;
  };

  if (durationMs < hourMs) {
    return `${formatDay(range.start)} ${formatTime(range.start, {
      withMinutes: true,
      withSeconds: true,
    })} → ${formatDay(range.end)} ${formatTime(range.end, {
      withMinutes: true,
      withSeconds: true,
    })}`;
  }

  if (durationMs < dayMs) {
    return `${formatDay(range.start)} ${formatTime(range.start, {
      withMinutes: true,
      withSeconds: false,
    })} → ${formatDay(range.end)} ${formatTime(range.end, {
      withMinutes: true,
      withSeconds: false,
    })}`;
  }

  if (durationMs < threeDaysMs) {
    return `${formatDay(range.start)} ${formatTime(range.start, {
      withMinutes: false,
      withSeconds: false,
    })} → ${formatDay(range.end)} ${formatTime(range.end, {
      withMinutes: false,
      withSeconds: false,
    })}`;
  }

  return `${formatDay(range.start)} → ${formatDay(range.end)}`;
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
