import type { RequestLogStats, VramV2Sample, TimelineEnqueueEvent, VramSeriesPoint, VramProviderPayload, RequestItem, PaginatedRequestItem } from './statistics.models';
import { cssVar } from './statistics.constants';

// ── Recent-Requests helpers (ported from paginated-request-list.tsx) ──────────

export type RequestStage = 'queued' | 'executing' | 'complete';

export function deriveStage(item: PaginatedRequestItem): RequestStage {
  if (item.request_complete_ts) return 'complete';
  if (item.scheduled_ts) return 'executing';
  return 'queued';
}

export function getRequestBorderColor(stage: RequestStage, status: string): string {
  if (stage === 'queued') return cssVar('--color-accent-purple');
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

export function mergeWithLive(
  liveRequests: RequestItem[],
  pageItems: PaginatedRequestItem[],
  perPage: number
): PaginatedRequestItem[] {
  const toPaginated = (r: RequestItem): PaginatedRequestItem => ({
    request_id: r.request_id,
    model_name: r.model_name,
    provider_name: r.provider_name,
    // infer is_cloud from provider name (fallback when paginated
    // endpoint hasn't returned yet — pageData carries the real flag).
    is_cloud:
      r.provider_name?.toLowerCase().includes('openai') ||
      r.provider_name?.toLowerCase().includes('azure') ||
      r.provider_name?.toLowerCase().includes('cloud'),
    status: r.status,
    timestamp: r.timestamp,
    duration: r.duration,
    cold_start: r.cold_start,
    enqueue_ts: r.enqueue_ts,
    scheduled_ts: r.scheduled_ts,
    request_complete_ts: r.request_complete_ts,
    queue_seconds: r.queue_seconds,
    total_seconds: r.total_seconds,
    initial_priority: r.initial_priority,
    priority_when_scheduled: r.priority_when_scheduled,
    queue_depth_at_enqueue: r.queue_depth_at_enqueue,
    error_message: r.error_message,
  });

  const liveById = new Map<string, PaginatedRequestItem>();
  for (const r of liveRequests) {
    liveById.set(r.request_id, toPaginated(r));
  }

  const merged: PaginatedRequestItem[] = [];
  const seen = new Set<string>();
  for (const p of pageItems) {
    const overlay = liveById.get(p.request_id);
    if (overlay) {
      // Preserve the paginated `is_cloud` flag (the WS payload has to
      // infer it from the provider name); take everything else from
      // the live row so state transitions render immediately.
      merged.push({ ...overlay, is_cloud: p.is_cloud ?? overlay.is_cloud });
    } else {
      merged.push(p);
    }
    seen.add(p.request_id);
  }
  for (const [id, r] of liveById) {
    if (!seen.has(id)) merged.push(r);
  }

  return merged
    .sort((a, b) => {
      const aTs = a.enqueue_ts ?? a.timestamp ?? '';
      const bTs = b.enqueue_ts ?? b.timestamp ?? '';
      return bTs.localeCompare(aTs);
    })
    .slice(0, perPage);
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
