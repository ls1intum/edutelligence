import type { RequestLogStats, VramV2Sample, TimelineEnqueueEvent, VramSeriesPoint, VramProviderPayload } from './statistics.models';
import { cssVar } from './statistics.constants';

// ── Recent-Requests helpers (ported from paginated-request-list.tsx) ──────────

export type RequestStage = 'queued' | 'executing' | 'complete';

export function deriveStage(
  item: { request_complete_ts: string | null; scheduled_ts: string | null },
): RequestStage {
  if (item.request_complete_ts) return 'complete';
  if (item.scheduled_ts) return 'executing';
  return 'queued';
}

export function getRequestBorderColor(stage: RequestStage, status: string): string {
  if (stage === 'queued') return cssVar('--color-primary-500');
  if (stage === 'executing') return cssVar('--color-accent-cyan');
  switch (status.toLowerCase()) {
    case 'success': return cssVar('--color-success');
    case 'error':   return cssVar('--color-error');
    case 'timeout': return cssVar('--color-warning');
    default:        return cssVar('--color-typography-500');
  }
}

export function formatTimeAgo(ts: string | null, nowMs: number): string {
  if (!ts) return '';
  const diffS = Math.max(0, (nowMs - new Date(ts).getTime()) / 1000);
  if (diffS < 60) return `${Math.round(diffS)}s ago`;
  const diffM = diffS / 60;
  if (diffM < 60) return `${Math.round(diffM)}m ago`;
  const diffH = diffM / 60;
  if (diffH < 24) return `${Math.round(diffH)}h ago`;
  return `${Math.round(diffH / 24)}d ago`;
}

export function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s}s`;
}

// ── Token count scale ─────────────────────────────────────────────────────────

/**
 * The scale a token count is displayed on: the unit steps up the moment the
 * value leaves its range — K at 1.000, M at 1.000.000, B at 1.000.000.000,
 * T at 1.000.000.000.000.
 */
const TOKEN_COUNT_UNITS: ReadonlyArray<{ value: number; label: string }> = [
  { value: 1_000, label: 'K' },
  { value: 1_000_000, label: 'M' },
  { value: 1_000_000_000, label: 'B' },
  { value: 1_000_000_000_000, label: 'T' },
];

/**
 * A token count on the K/M/B/T scale: always the highest applicable
 * magnitude, a space between the value and the unit, and the value's decimal
 * notation kept — the 2470.7M the statistics page used to show reads "2.4 B".
 * Counts below 1.000 stay plain; input that is not a positive finite number
 * reads "0".
 *
 * The value is truncated to one decimal, dropped when it is zero. One digit
 * after the dot keeps the dot unambiguous — a thousands group is three
 * digits, never one — and it keeps the abbreviation shorter than the number
 * it replaces (262.1 K instead of 262,144).
 */
export function formatTokenCount(count: number | null | undefined): string {
  if (typeof count !== 'number' || !Number.isFinite(count) || count <= 0) return '0';
  if (count < 1_000) return String(Math.round(count));
  // The early return guarantees count >= 1.000, so K always matches and the
  // walk from K up ends on the highest unit the count reaches.
  const unit = TOKEN_COUNT_UNITS.reduce(
    (highest, u) => (count >= u.value ? u : highest),
    TOKEN_COUNT_UNITS[0],
  );
  const tenths = Math.floor(count / (unit.value / 10));
  return `${(tenths / 10).toFixed(1).replace(/\.0$/, '')} ${unit.label}`;
}

// ── X-axis labels (shared by request-volume and VRAM charts) ─────────────────

export interface TimeAxisLabel {
  tsMs: number;
  label: string;
}

const MONTHS_SHORT = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

const DAY_MS = 86_400_000;
const HOUR_MS = 3_600_000;

/**
 * Deterministic, unambiguous x-axis labels for a time window:
 * - span ≤ 24 h   → "HH:00" at hour boundaries (hours are unique within 24 h)
 * - span ≤ 32 d   → "Mon D" at day boundaries (the month prefix keeps labels
 *                   unique, e.g. "Jul 30" vs "Aug 30" never collide)
 * - span >  32 d  → "Mon YYYY" at month boundaries
 * Labels are thinned to at most `maxLabels`, keeping the first of each step.
 *
 * All boundaries and labels are in the **viewer's local time**, because that is
 * what the range selection means: `calendarRange` builds "Today" from local
 * midnight and `periodLabel` names it in local terms. Ticking in UTC put the
 * axis of a "Today" view hours off its own heading for anyone east or west of
 * Greenwich — a request made at 14:00 sat under the 12:00 tick in Munich.
 *
 * Boundaries are stepped through a Date rather than by adding a fixed number of
 * milliseconds, so a DST switch inside the window does not drag every later
 * label off its hour.
 *
 * When a window is too short to contain a single boundary of its own tier
 * (a 20-minute "Today" view, a single-bucket chart), the boundaries are
 * replaced by evenly spaced ticks so the axis is never left blank.
 */
export function timeAxisLabels(
  winStartMs: number,
  winEndMs: number,
  maxLabels = 8,
): TimeAxisLabel[] {
  if (!Number.isFinite(winStartMs) || !Number.isFinite(winEndMs) || winEndMs <= winStartMs) {
    return [];
  }
  const spanMs = winEndMs - winStartMs;

  if (spanMs <= 24 * HOUR_MS) {
    const out: TimeAxisLabel[] = [];
    const cursor = new Date(winStartMs);
    cursor.setMinutes(0, 0, 0);
    if (cursor.getTime() < winStartMs) cursor.setHours(cursor.getHours() + 1);
    while (cursor.getTime() < winEndMs) {
      out.push({ tsMs: cursor.getTime(), label: hourLabel(cursor.getTime()) });
      cursor.setHours(cursor.getHours() + 1);
    }
    return out.length > 0
      ? thinLabels(out, maxLabels)
      : evenlySpacedLabels(winStartMs, winEndMs, maxLabels, clockLabel);
  }

  if (spanMs <= 32 * DAY_MS) {
    const out: TimeAxisLabel[] = [];
    const cursor = new Date(winStartMs);
    cursor.setHours(0, 0, 0, 0);
    if (cursor.getTime() < winStartMs) cursor.setDate(cursor.getDate() + 1);
    while (cursor.getTime() < winEndMs) {
      out.push({ tsMs: cursor.getTime(), label: dayLabel(cursor.getTime()) });
      cursor.setDate(cursor.getDate() + 1);
    }
    return out.length > 0
      ? thinLabels(out, maxLabels)
      : evenlySpacedLabels(winStartMs, winEndMs, maxLabels, dayLabel);
  }

  // Month boundaries inside the window.
  const out: TimeAxisLabel[] = [];
  const cursor = new Date(winStartMs);
  cursor.setHours(0, 0, 0, 0);
  // Day first: setMonth() on the 31st would skip a 30-day month entirely.
  cursor.setDate(1);
  if (cursor.getTime() < winStartMs) cursor.setMonth(cursor.getMonth() + 1);
  while (cursor.getTime() < winEndMs) {
    out.push({
      tsMs: cursor.getTime(),
      label: `${MONTHS_SHORT[cursor.getMonth()]} ${cursor.getFullYear()}`,
    });
    cursor.setMonth(cursor.getMonth() + 1);
  }
  return out.length > 0
    ? thinLabels(out, maxLabels)
    : evenlySpacedLabels(winStartMs, winEndMs, maxLabels, dayLabel);
}

function hourLabel(tsMs: number): string {
  return `${String(new Date(tsMs).getHours()).padStart(2, '0')}:00`;
}

function clockLabel(tsMs: number): string {
  const d = new Date(tsMs);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function dayLabel(tsMs: number): string {
  const d = new Date(tsMs);
  return `${MONTHS_SHORT[d.getMonth()]} ${d.getDate()}`;
}

/** Fallback ticks for windows that contain no boundary of their own tier. */
function evenlySpacedLabels(
  winStartMs: number,
  winEndMs: number,
  maxLabels: number,
  format: (tsMs: number) => string,
): TimeAxisLabel[] {
  const count = Math.min(Math.max(maxLabels, 1), 4);
  if (count === 1) {
    const mid = Math.round(winStartMs + (winEndMs - winStartMs) / 2);
    return [{ tsMs: mid, label: format(mid) }];
  }
  const step = (winEndMs - winStartMs) / (count - 1);
  const out: TimeAxisLabel[] = [];
  for (let i = 0; i < count; i++) {
    const ts = Math.round(winStartMs + i * step);
    const label = format(ts);
    if (out.length > 0 && out[out.length - 1].label === label) continue;
    out.push({ tsMs: ts, label });
  }
  return out;
}

/** Keep every n-th label so at most `max` survive (first label always kept). */
function thinLabels<T extends TimeAxisLabel>(labels: T[], max: number): T[] {
  if (labels.length <= max) return labels;
  const step = Math.ceil(labels.length / max);
  return labels.filter((_, i) => i % step === 0).slice(0, max);
}

// ── SVG Donut Arc ─────────────────────────────────────────────────────────────

/**
 * Computes the SVG path `d` attribute for an annular (donut) segment.
 *
 * @param cx        - X coordinate of circle centre
 * @param cy        - Y coordinate of circle centre
 * @param rOuter    - Outer radius
 * @param rInner    - Inner radius
 * @param startAngle - Start angle in radians (0 = top, clockwise)
 * @param endAngle   - End angle in radians
 * @returns SVG path string beginning with 'M'
 */
export function donutArc(
  cx: number,
  cy: number,
  rOuter: number,
  rInner: number,
  startAngle: number,
  endAngle: number
): string {
  // Clamp endAngle so we never draw a full 360° which collapses to nothing
  const safeEnd = Math.min(endAngle, startAngle + 2 * Math.PI - 0.0001);

  const cos = Math.cos;
  const sin = Math.sin;

  // SVG angles: 0 = top (–π/2), clockwise
  const a1 = startAngle - Math.PI / 2;
  const a2 = safeEnd - Math.PI / 2;

  const largeArc = safeEnd - startAngle > Math.PI ? 1 : 0;

  const x1 = cx + rOuter * cos(a1);
  const y1 = cy + rOuter * sin(a1);
  const x2 = cx + rOuter * cos(a2);
  const y2 = cy + rOuter * sin(a2);
  const x3 = cx + rInner * cos(a2);
  const y3 = cy + rInner * sin(a2);
  const x4 = cx + rInner * cos(a1);
  const y4 = cy + rInner * sin(a1);

  return [
    `M ${x1} ${y1}`,
    `A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${x2} ${y2}`,
    `L ${x3} ${y3}`,
    `A ${rInner} ${rInner} 0 ${largeArc} 0 ${x4} ${y4}`,
    'Z',
  ].join(' ');
}

// ── Constants ───────────────────────────────────────────────────────────────

export const BYTES_PER_MIB = 1024 * 1024;
export const BYTES_PER_GIB = 1024 * 1024 * 1024;

// ── From logos-ui-old/lib/utils/statistics.ts ───────────────────────────────

export function formatRangeLabel(range: { start: Date; end: Date }): string {
  const dayMs = 24 * 60 * 60 * 1000;
  const hourMs = 60 * 60 * 1000;
  const threeDaysMs = 3 * dayMs;
  const durationMs = Math.max(range.end.getTime() - range.start.getTime(), 0);

  const formatDay = (d: Date) =>
    `${d.getDate().toString().padStart(2, '0')}/${(d.getMonth() + 1)
      .toString()
      .padStart(2, '0')}`;

  const formatTime = (
    d: Date,
    opts: { withMinutes: boolean; withSeconds: boolean }
  ) => {
    const hours = d.getHours();
    const hours12 = hours % 12 || 12;
    const meridiem = hours >= 12 ? 'pm' : 'am';
    const minutes = d.getMinutes().toString().padStart(2, '0');
    const seconds = d.getSeconds().toString().padStart(2, '0');

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
    })} › ${formatDay(range.end)} ${formatTime(range.end, {
      withMinutes: true,
      withSeconds: true,
    })}`;
  }

  if (durationMs < dayMs) {
    return `${formatDay(range.start)} ${formatTime(range.start, {
      withMinutes: true,
      withSeconds: false,
    })} › ${formatDay(range.end)} ${formatTime(range.end, {
      withMinutes: true,
      withSeconds: false,
    })}`;
  }

  if (durationMs < threeDaysMs) {
    return `${formatDay(range.start)} ${formatTime(range.start, {
      withMinutes: false,
      withSeconds: false,
    })} › ${formatDay(range.end)} ${formatTime(range.end, {
      withMinutes: false,
      withSeconds: false,
    })}`;
  }

  return `${formatDay(range.start)} › ${formatDay(range.end)}`;
}

export const applyTimeSeriesLabels = (
  series: RequestLogStats['timeSeries'],
  rangeStart: Date,
  rangeEnd: Date
): RequestLogStats['timeSeries'] => {
  if (!series.length) return [];

  const durationMs = Math.max(rangeEnd.getTime() - rangeStart.getTime(), 0);
  const labelStep = Math.max(1, Math.ceil(series.length / 5)); // halve the label count
  let lastLabel = '';

  return series.map((pt, idx) => {
    const next = { ...pt };
    if (idx % labelStep === 0) {
      const date = new Date(pt.timestamp);
      let newLabel = '';
      if (durationMs < 24 * 3600 * 1000) {
        newLabel = date.toLocaleTimeString('en-GB', {
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
        });
      } else if (durationMs < 7 * 24 * 3600 * 1000) {
        newLabel =
          date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) +
          ` ${date.getHours()}h`;
      } else {
        newLabel = date.toLocaleDateString('en-US', {
          month: 'short',
          day: 'numeric',
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

  if (period === 'custom' && customRange) {
    return { startDate: customRange.start, endDate: customRange.end };
  }

  switch (period) {
    case '24h':
      startDate.setHours(startDate.getHours() - 24);
      break;
    case '7d':
      startDate.setDate(startDate.getDate() - 7);
      break;
    case '30d':
      startDate.setDate(startDate.getDate() - 30);
      break;
  }

  return { startDate, endDate };
};

// ── From logos-ui-old/app/statistics.tsx ────────────────────────────────────

// Binary GiB (labelled "GB" in the UI, matching nvidia-smi / the nominal GPU spec).
// The rest of the stats page (VRAM chart, worker GPU panel, lane pie) already uses
// binary GiB, so this keeps every VRAM number consistent.
export const toGb = (bytes: number) => Number((bytes / BYTES_PER_GIB).toFixed(2));

export const getLoadedModelSizeBytes = (model: any): number => {
  if (typeof model?.size_vram === 'number' && model.size_vram > 0) {
    return model.size_vram;
  }
  if (typeof model?.size_vram_mb === 'number' && model.size_vram_mb > 0) {
    return model.size_vram_mb * BYTES_PER_MIB;
  }
  if (typeof model?.size === 'number' && model.size > 0) {
    return model.size;
  }
  if (typeof model?.size_mb === 'number' && model.size_mb > 0) {
    return model.size_mb * BYTES_PER_MIB;
  }
  return 0;
};

export const getLoadedModelsFromRaw = (
  raw: any
): Array<{ name: string; size_gb: number }> =>
  (raw?.loaded_models || [])
    .map((m: any) => {
      const sizeBytes = getLoadedModelSizeBytes(m);
      return {
        name: m?.name ?? m?.model ?? 'model',
        size_gb: toGb(sizeBytes),
      };
    })
    .filter((m: any) => m.size_gb > 0);

export const parseVramSnapshot = (raw: any) => {
  const usedBytes =
    typeof raw?.vram_bytes === 'number'
      ? raw.vram_bytes
      : (raw?.used_vram_mb || raw?.vram_mb || 0) * BYTES_PER_MIB;
  const configuredTotalBytes = (raw?.total_vram_mb || 0) * BYTES_PER_MIB;
  const remainingBytes =
    raw?.remaining_vram_mb != null
      ? raw.remaining_vram_mb * BYTES_PER_MIB
      : Math.max(0, configuredTotalBytes - usedBytes);
  const loadedModels = getLoadedModelsFromRaw(raw);

  // Prefer the reported hardware total; `used + remaining` mixes two accounting systems.
  const totalBytes = configuredTotalBytes > 0 ? configuredTotalBytes : usedBytes + remainingBytes;

  return {
    usedGb: toGb(usedBytes),
    remainingGb: toGb(remainingBytes),
    totalGb: toGb(totalBytes),
    modelsLoaded: raw?.models_loaded ?? loadedModels.length,
    loadedModels,
  };
};

export const toVramSeriesPoint = (
  raw: any,
  timestamp: number,
  label = ''
): VramSeriesPoint => {
  const snapshot = parseVramSnapshot(raw);
  return {
    value: snapshot.remainingGb,
    label,
    timestamp,
    used_vram_gb: snapshot.usedGb,
    remaining_vram_gb: snapshot.remainingGb,
    total_vram_gb: snapshot.totalGb,
    models_loaded: snapshot.modelsLoaded,
    loaded_model_names: snapshot.loadedModels.map((m: { name: string; size_gb: number }) => m.name),
    loaded_models: snapshot.loadedModels,
    _empty: false,
  };
};

/**
 * Single source of truth for a sample's VRAM in MB. Prefers the authoritative
 * nvidia-smi figures (scheduler_signals.provider), falling back to the legacy
 * top-level fields. Used for both per-provider and all-provider summaries.
 */
export const extractProviderVramMb = (
  sample: VramV2Sample | null | undefined
): { totalMb: number; usedMb: number; freeMb: number } => {
  const prov = sample?.scheduler_signals?.provider;
  const totalMb = prov?.total_memory_mb ?? sample?.total_vram_mb ?? 0;
  const freeMb = prov?.free_memory_mb ?? sample?.remaining_vram_mb ?? 0;
  const usedMb = prov?.used_memory_mb ?? Math.max(0, totalMb - freeMb);
  return { totalMb, usedMb, freeMb };
};

export const buildVramSignature = (
  providers: VramProviderPayload[]
): string =>
  [...providers]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((provider) => {
      const last = provider.data?.[provider.data.length - 1] || {};
      const models = Array.isArray(last.loaded_models)
        ? last.loaded_models
            .map((m: any) => `${m.name}:${m.size_vram_mb ?? m.size_vram ?? ''}`)
            .join('|')
        : '';
      return [
        provider.name,
        provider.connection_state ?? '',
        (provider.runtime_modes || []).join('|'),
        last.timestamp ?? '',
        last.used_vram_mb ?? last.vram_mb ?? '',
        last.remaining_vram_mb ?? '',
        last.total_vram_mb ?? '',
        models,
      ].join('::');
    })
    .join('||');

export const chooseDynamicTargetBuckets = (spanMs: number): number => {
  const hour = 60 * 60 * 1000;
  const day = 24 * hour;

  if (spanMs > 30 * day) return 90;
  if (spanMs > 7 * day) return 96;
  if (spanMs > day) return 108;
  return 120;
};

export const chooseDynamicBucketMs = (spanMs: number): number => {
  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const safeSpanMs = Math.max(spanMs, minute);
  const targetBuckets = chooseDynamicTargetBuckets(safeSpanMs);
  const rawBucketMs = Math.max(safeSpanMs / targetBuckets, minute);
  const niceCandidates = [
    minute,
    5 * minute,
    15 * minute,
    30 * minute,
    hour,
    3 * hour,
    6 * hour,
    12 * hour,
    day,
  ];

  return niceCandidates.reduce((best, candidate) =>
    Math.abs(candidate - rawBucketMs) < Math.abs(best - rawBucketMs)
      ? candidate
      : best
  );
};

export const aggregateEventsToVolumeSeries = (
  events: TimelineEnqueueEvent[],
  startMs: number,
  endMs: number,
  bucketMs: number
): RequestLogStats['timeSeries'] => {
  const safeBucketMs = Math.max(bucketMs, 30 * 1000);
  const alignedStart = Math.floor(startMs / safeBucketMs) * safeBucketMs;
  const alignedEnd = Math.ceil(endMs / safeBucketMs) * safeBucketMs;
  const buckets = new Map<
    number,
    { cloud: number; local: number; total: number }
  >();

  for (let ts = alignedStart; ts <= alignedEnd; ts += safeBucketMs) {
    buckets.set(ts, { cloud: 0, local: 0, total: 0 });
  }

  for (const event of events) {
    const ts = Number(event.timestamp_ms);
    if (!Number.isFinite(ts) || ts < alignedStart || ts > alignedEnd)
      continue;
    const bucketTs = Math.floor(ts / safeBucketMs) * safeBucketMs;
    const bucket = buckets.get(bucketTs) || {
      cloud: 0,
      local: 0,
      total: 0,
    };
    if (event.is_cloud) bucket.cloud += 1;
    else bucket.local += 1;
    bucket.total += 1;
    buckets.set(bucketTs, bucket);
  }

  const rawSeries: RequestLogStats['timeSeries'] = [];
  for (const [timestamp, bucket] of buckets.entries()) {
    rawSeries.push({
      timestamp,
      label: '',
      cloud: bucket.cloud,
      local: bucket.local,
      total: bucket.total,
      avgRunSeconds: null,
      avgVram: null,
    });
  }

  rawSeries.sort((a, b) => a.timestamp - b.timestamp);
  return applyTimeSeriesLabels(
    rawSeries,
    new Date(alignedStart),
    new Date(alignedEnd)
  );
};
