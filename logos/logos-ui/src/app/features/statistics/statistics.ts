import {
  Component,
  computed,
  effect,
  afterRenderEffect,
  ElementRef,
  inject,
  OnDestroy,
  OnInit,
  signal,
  viewChild,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';

import { StatsWebsocketService } from './services/stats-websocket.service';

import { CHART_ROLE, getLaneStateColor, seriesColor, STATUS_COLOR } from './statistics.constants';

import {
  aggregateEventsToVolumeSeries,
  applyTimeSeriesLabels,
  chooseDynamicBucketMs,
  chooseDynamicTargetBuckets,
  extractProviderHostRamMb,
  extractProviderVramMb,
  formatRangeLabel,
  formatTokenCount as formatTokenCountValue,
  BYTES_PER_GIB,
  BYTES_PER_MIB,
  toGb,
  toVramSeriesPoint,
} from './statistics.utils';

import {
  TimePreset, calendarRange, periodLabel as periodLabelFn,
} from '../../shared/utils/time-range';
import { formatUsd } from '../../shared/utils/currency';
import { TimeRangeBarComponent } from '../../shared/components/time-range-bar/time-range-bar';

import type {
  DeviceInfo,
  FeedFilterOption,
  LaneSignalData,
  RequestItem,
  RequestLogStats,
  TimelineDeltaPayload,
  TimelineEnqueueEvent,
  TimelineInitPayload,
  VramProviderMeta,
  VramV2Payload,
  VramV2Sample,
} from './statistics.models';

// Child components
import { ChartPanel } from './components/chart-panel/chart-panel';
import { EmptyState } from './components/empty-state/empty-state';
import { LaneHealthPanel } from './components/lane-health-panel/lane-health-panel';
import { LaneVramPieComponent } from './components/lane-vram-pie/lane-vram-pie';
import { SelectComponent, AppSelectOption } from '../../shared/components/select/select';
import { RecentRequests } from './components/recent-requests/recent-requests';
import { StatisticsService } from './services/statistics.service';
import { RequestVolumeChartComponent, ChartTooltip } from './components/request-volume-chart/request-volume-chart';
import { SparklineComponent } from './components/sparkline/sparkline';
import { StatKpiCardComponent } from './components/stat-kpi-card/stat-kpi-card';
import { StatusBars } from './components/status-bars/status-bars';
import { StatsSkeletonComponent } from './components/skeletons/skeletons';
import { VramDonutComponent } from './components/vram-donut/vram-donut';
import { VramRemainingChartComponent } from './components/vram-remaining-chart/vram-remaining-chart';
import { WorkerGpuPanel } from './components/worker-gpu-panel/worker-gpu-panel';

// ── Raw VRAM cap ──────────────────────────────────────────────────────────────
const RAW_VRAM_SAMPLE_CAP = 720;

/**
 * Ceiling on the accumulated enqueue events the volume chart re-buckets. Matches
 * the server's own cap on the initial load, so a session that has been open for
 * hours holds no more than a fresh one would.
 */
const TIMELINE_EVENT_CAP = 200_000;

@Component({
  selector: 'app-statistics',
  standalone: true,
  imports: [
    CommonModule,
    ChartPanel,
    EmptyState,
    LaneHealthPanel,
    LaneVramPieComponent,
    SelectComponent,
    RecentRequests,
    RequestVolumeChartComponent,
    SparklineComponent,
    StatKpiCardComponent,
    StatusBars,
    StatsSkeletonComponent,
    VramDonutComponent,
    VramRemainingChartComponent,
    WorkerGpuPanel,
    TimeRangeBarComponent,
  ],
  templateUrl: './statistics.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './statistics.scss',
})
export class Statistics implements OnInit, OnDestroy {
  private statsWs = inject(StatsWebsocketService);
  private statisticsService = inject(StatisticsService);

  /** Filter options, loaded once on init. */
  readonly feedUsers = signal<FeedFilterOption[]>([]);
  readonly feedTeams = signal<FeedFilterOption[]>([]);

  // ── Scope ─────────────────────────────────────────────────────────────────
  // Null on either side means "everyone". The filter lives on the page rather
  // than inside the request feed, because it applies to the page: narrowing the
  // list while the KPI cards and charts above it kept counting the whole
  // platform left the two halves of the screen describing different things.
  //
  // Deliberately not applied to VRAM, lanes or GPUs. Those are properties of
  // the hardware and are not attributable to a team, so filtering them would
  // not be a narrower truth — it would be no data at all.
  readonly filterUserId = signal<number | null>(null);
  readonly filterTeamId = signal<number | null>(null);

  readonly filterActive = computed(
    () => this.filterUserId() !== null || this.filterTeamId() !== null,
  );

  // Both lists carry their request count, so the dropdown says which entries
  // are worth opening instead of being an alphabet of names. Ordered busiest
  // first by the server, which only reads as deliberate once the numbers show.
  readonly userFilterOptions = computed<AppSelectOption[]>(() => [
    {
      value: '',
      label: this.filterTeamId() === null ? 'All requesters' : 'Everyone in this team',
    },
    ...this.feedUsers().map((u) => ({
      value: String(u.id),
      label: `${u.label} (${u.requestCount.toLocaleString()})`,
    })),
  ]);

  readonly teamFilterOptions = computed<AppSelectOption[]>(() => [
    { value: '', label: 'All teams' },
    ...this.feedTeams().map((t) => ({
      value: String(t.id),
      label: `${t.label} (${t.requestCount.toLocaleString()})`,
    })),
  ]);

  /**
   * Nobody in the selected team sent anything in this range, so the requester
   * dropdown has nothing but its "everyone" entry. Worth saying outright — an
   * empty picker otherwise reads as a page that failed to load its options.
   */
  readonly noRequestersInScope = computed(
    () => this.feedUsers().length === 0 && this.feedTeams().length > 0,
  );

  readonly selectedUserValue = computed(() => {
    const id = this.filterUserId();
    return id === null ? '' : String(id);
  });

  readonly selectedTeamValue = computed(() => {
    const id = this.filterTeamId();
    return id === null ? '' : String(id);
  });

  /** What the active filter narrows to, for the label above the KPI strip. */
  readonly filterLabel = computed(() => {
    const parts: string[] = [];
    const teamId = this.filterTeamId();
    if (teamId !== null) {
      parts.push(this.feedTeams().find((t) => t.id === teamId)?.label ?? `team ${teamId}`);
    }
    const userId = this.filterUserId();
    if (userId !== null) {
      parts.push(this.feedUsers().find((u) => u.id === userId)?.label ?? `user ${userId}`);
    }
    return parts.join(' · ');
  });

  // ── Raw WS signals ────────────────────────────────────────────────────────────
  readonly stats = signal<RequestLogStats | null>(null);
  readonly vramRawDataByProvider = signal<Record<string, VramV2Sample[]>>({});
  readonly vramProviderMetaByName = signal<Record<string, VramProviderMeta>>({});
  readonly devicesByProvider = signal<Record<string, DeviceInfo[]>>({});
  readonly latestRequests = signal<RequestItem[]>([]);
  readonly timelineEvents = signal<TimelineEnqueueEvent[]>([]);
  readonly selectedVramProvider = signal<string | null>(null);
  readonly customRange = signal<{ start: Date; end: Date } | null>(null);
  readonly error = signal<string | null>(null);
  readonly vramError = signal<string | null>(null);
  readonly isVramLoading = signal(false);
  readonly nowMs = signal(Date.now());
  readonly refreshing = signal(false);
  readonly resetZoomCounter = signal(0);
  readonly chartTooltip = signal<ChartTooltip | null>(null);
  private readonly chartTooltipEl = viewChild<ElementRef<HTMLElement>>('chartTooltipEl');

  // ── Preset / time-range-bar state ─────────────────────────────────────────────
  readonly preset = signal<TimePreset>('30d');
  readonly offset = signal(0);
  readonly presetRange = computed(() => calendarRange(this.preset(), this.offset()));
  readonly periodLabel = computed(() =>
    periodLabelFn(this.preset(), this.offset(), this.presetRange()),
  );

  // Internal: stored timeline range for derived series
  private timelineRangeMs: { startMs: number; endMs: number; bucketMs: number } | null = null;
  private hasResolvedStats = false;

  /**
   * A range change is in flight — every number on the page still describes the
   * *previous* range until the next `timeline_init` / `requests` push lands.
   * Without these flags the cards keep their old values while the header
   * already says the new period, which reads as data for a range it isn't.
   */
  readonly statsPending = signal(false);
  /** Starts true: the first push has not landed, so there is nothing to show yet. */
  readonly requestsPending = signal(true);

  // ── Ticker ────────────────────────────────────────────────────────────────────
  private nowInterval: ReturnType<typeof setInterval> | null = null;

  // ── wsTimelineConfig ─────────────────────────────────────────────────────────
  readonly wsTimelineConfig = computed(() => {
    const cr = this.customRange();
    let startDate: Date;
    let endDate: Date;
    if (cr) {
      startDate = cr.start;
      endDate = cr.end;
    } else {
      const r = this.presetRange();
      startDate = r.currStart;
      // currEnd is the exclusive next-period midnight (e.g. Jul 1 for June).
      // Cap at now so we don't request future buckets, and subtract 1ms so
      // the backend doesn't include a stray midnight bucket from the next period.
      endDate = new Date(Math.min(r.currEnd.getTime() - 1, Date.now()));
    }
    const spanMs = Math.max(endDate.getTime() - startDate.getTime(), 60 * 1000);
    return {
      start: startDate.toISOString(),
      end: endDate.toISOString(),
      targetBuckets: chooseDynamicTargetBuckets(spanMs),
    };
  });

  // ── Provider derivations ──────────────────────────────────────────────────────

  readonly vramProviders = computed(() => Object.keys(this.vramRawDataByProvider()).sort());

  readonly vramProviderOptions = computed<AppSelectOption[]>(() =>
    this.vramProviders().map((p) => ({
      value: p,
      label: this._isProviderOnline(p) ? p : `${p} (offline)`,
    })),
  );

  readonly latestVramSample = computed<VramV2Sample | null>(() => {
    const prov = this.selectedVramProvider();
    if (!prov) return null;
    const rawSeries = this.vramRawDataByProvider()[prov] || [];
    if (!rawSeries.length) return null;
    const raw = rawSeries[rawSeries.length - 1];
    if (!raw?.timestamp) return null;
    return raw as VramV2Sample;
  });

  readonly latestVramPoint = computed(() => {
    const raw = this.latestVramSample();
    if (!raw) return null;
    return toVramSeriesPoint(raw, new Date(raw.timestamp).getTime());
  });

  readonly lanesByProvider = computed<Record<string, Record<string, LaneSignalData>>>(() => {
    const result: Record<string, Record<string, LaneSignalData>> = {};
    for (const [providerName, samples] of Object.entries(this.vramRawDataByProvider())) {
      if (!samples.length) continue;
      const latest = samples[samples.length - 1] as VramV2Sample | undefined;
      const lanes = latest?.scheduler_signals?.lanes;
      if (lanes && typeof lanes === 'object') {
        result[providerName] = lanes;
      }
    }
    return result;
  });

  readonly onlineLanesByProvider = computed<Record<string, Record<string, LaneSignalData>>>(() => {
    const result: Record<string, Record<string, LaneSignalData>> = {};
    for (const [name, lanes] of Object.entries(this.lanesByProvider())) {
      if (this._isProviderOnline(name)) result[name] = lanes;
    }
    return result;
  });

  readonly latestSampleByProvider = computed<Record<string, VramV2Sample | null>>(() => {
    const result: Record<string, VramV2Sample | null> = {};
    for (const [providerName, samples] of Object.entries(this.vramRawDataByProvider())) {
      result[providerName] = samples.length ? (samples[samples.length - 1] as VramV2Sample) : null;
    }
    return result;
  });

  readonly laneStateCounts = computed(() => {
    const out = {
      loaded: 0,
      running: 0,
      starting: 0,
      sleeping: 0,
      cold: 0,
      stopped: 0,
      error: 0,
      activeRequests: 0,
      total: 0,
    };
    for (const lanes of Object.values(this.onlineLanesByProvider())) {
      for (const lane of Object.values(lanes)) {
        out.total += 1;
        out.activeRequests += lane.active_requests || 0;
        switch (lane.runtime_state) {
          case 'loaded':
            out.loaded += 1;
            break;
          case 'running':
            out.running += 1;
            break;
          case 'starting':
            out.starting += 1;
            break;
          case 'sleeping':
            out.sleeping += 1;
            break;
          case 'cold':
            out.cold += 1;
            break;
          case 'stopped':
            out.stopped += 1;
            break;
          case 'error':
            out.error += 1;
            break;
        }
      }
    }
    return out;
  });

  readonly derivedActiveLanes = computed(() => {
    const c = this.laneStateCounts();
    return c.loaded + c.running + c.starting;
  });

  readonly allProviderVramSummary = computed(() => {
    let totalMb = 0;
    let usedMb = 0;
    let freeMb = 0;
    for (const [name, sample] of Object.entries(this.latestSampleByProvider())) {
      if (!this._isProviderOnline(name)) continue;
      const vram = extractProviderVramMb(sample);
      totalMb += vram.totalMb;
      freeMb += vram.freeMb;
      usedMb += vram.usedMb;
    }
    return {
      usedGb: toGb(usedMb * BYTES_PER_MIB),
      freeGb: toGb(freeMb * BYTES_PER_MIB),
      totalGb: toGb(totalMb * BYTES_PER_MIB),
    };
  });

  /**
   * Host RAM across the online providers, parallel to allProviderVramSummary.
   * A provider that does not report host RAM (an older worker, or a non-Linux
   * host) is skipped rather than counted as 0 — adding it in would make the
   * total visibly shrink every time such a node came online.
   */
  readonly allProviderRamSummary = computed(() => {
    let totalMb = 0;
    let usedMb = 0;
    let freeMb = 0;
    for (const [name, sample] of Object.entries(this.latestSampleByProvider())) {
      if (!this._isProviderOnline(name)) continue;
      const ram = extractProviderHostRamMb(sample);
      if (!ram.reported) continue;
      totalMb += ram.totalMb;
      usedMb += ram.usedMb;
      freeMb += ram.freeMb;
    }
    return {
      reported: totalMb > 0,
      usedGb: toGb(usedMb * BYTES_PER_MIB),
      freeGb: toGb(freeMb * BYTES_PER_MIB),
      totalGb: toGb(totalMb * BYTES_PER_MIB),
    };
  });

  readonly selectedProviderLanes = computed<Record<string, LaneSignalData>>(() => {
    const prov = this.selectedVramProvider();
    if (!prov) return {};
    return this.lanesByProvider()[prov] ?? {};
  });

  readonly selectedProviderTotalVramMb = computed(() => {
    const prov = this.selectedVramProvider();
    if (!prov) return 0;
    return extractProviderVramMb(this.latestSampleByProvider()[prov]).totalMb;
  });

  readonly hasSelectedProviderLanes = computed(
    () => Object.keys(this.selectedProviderLanes()).length > 0,
  );

  readonly selectedProviderFreeVramMb = computed(() => {
    const prov = this.selectedVramProvider();
    if (!prov) return 0;
    return extractProviderVramMb(this.latestSampleByProvider()[prov]).freeMb;
  });

  /**
   * Badge text for the selected provider's free VRAM, or null when there is no
   * sample to report. A provider whose memory is exhausted legitimately reports
   * 0 MB free, so absence has to be the missing sample rather than the value —
   * gating the badge on `> 0` hid exactly the state worth seeing.
   */
  readonly selectedProviderFreeVramLabel = computed<string | null>(() => {
    const prov = this.selectedVramProvider();
    if (!prov) return null;
    const sample = this.latestSampleByProvider()[prov];
    if (!sample) return null;
    return `${(extractProviderVramMb(sample).freeMb / 1024).toFixed(1)} GB free`;
  });

  readonly vramPieData = computed(() => {
    const pt = this.latestVramPoint();
    const usedGb = pt?.used_vram_gb ?? 0;
    const remainingGb = pt?.remaining_vram_gb ?? 0;
    const totalGb = pt?.total_vram_gb ?? usedGb + remainingGb;
    if (totalGb <= 0) return [];

    const reportedModels = pt?.loaded_models ?? [];
    const rawModelSlices = reportedModels
      .map((model, index) => ({
        value: Number(model.size_gb || 0),
        color: seriesColor(index),
        text: model.name,
      }))
      .filter((slice) => slice.value > 0);

    const attributedUsedGb = rawModelSlices.reduce((sum, s) => sum + s.value, 0);
    const modelScale =
      attributedUsedGb > usedGb && attributedUsedGb > 0 ? usedGb / attributedUsedGb : 1;
    const modelSlices = rawModelSlices.map((slice) => ({
      ...slice,
      value: Number((slice.value * modelScale).toFixed(3)),
    }));
    const modeledUsedGb = modelSlices.reduce((sum, s) => sum + s.value, 0);
    const otherUsedGb = Math.max(usedGb - modeledUsedGb, 0);

    return [
      ...modelSlices,
      {
        value: otherUsedGb,
        color: CHART_ROLE.total,
        text: modelSlices.length > 0 ? 'Other used' : 'Used',
      },
      {
        value: remainingGb,
        color: seriesColor(3),
        text: 'Free',
      },
    ].filter((s) => s.value > 0);
  });

  readonly vramSummary = computed(() => {
    const pt = this.latestVramPoint();
    const usedGb = pt?.used_vram_gb ?? 0;
    const remainingGb = pt?.remaining_vram_gb ?? 0;
    const totalGb = usedGb + remainingGb;
    const freePct = totalGb > 0 ? Math.round((remainingGb / totalGb) * 100) : 0;
    const models = pt?.loaded_models ?? [];
    const modelPreview =
      models.length > 0
        ? `${models
            .slice(0, 3)
            .map((m) => m.name)
            .join(', ')}${models.length > 3 ? ` +${models.length - 3} more` : ''}`
        : 'No models reported';
    return {
      usedGb,
      remainingGb,
      totalGb,
      freePct,
      modelsLoaded: pt?.models_loaded ?? models.length,
      modelPreview,
      models,
    };
  });

  // ── Volume line data ──────────────────────────────────────────────────────────

  readonly volumeSeries = computed(() => {
    const s = this.stats();
    if (!s?.timeSeries) {
      return { totalLineData: [], cloudLineData: [], localLineData: [] };
    }

    const tsSeries = s.timeSeries;
    const cr = this.customRange();

    const fallbackStart = tsSeries[0]?.timestamp ?? Date.now() - 30 * 24 * 3600 * 1000;
    const fallbackEnd = tsSeries[tsSeries.length - 1]?.timestamp ?? Date.now();
    const rangeStartMs = cr
      ? cr.start.getTime()
      : Math.min(this.timelineRangeMs?.startMs ?? fallbackStart, fallbackStart);
    const rangeEndMs = cr
      ? cr.end.getTime()
      : Math.max(this.timelineRangeMs?.endMs ?? fallbackEnd, fallbackEnd);

    if (
      !Number.isFinite(rangeStartMs) ||
      !Number.isFinite(rangeEndMs) ||
      rangeEndMs <= rangeStartMs
    ) {
      return { totalLineData: [], cloudLineData: [], localLineData: [] };
    }

    const bucketMs = chooseDynamicBucketMs(rangeEndMs - rangeStartMs);
    const events = this.timelineEvents();
    let series: RequestLogStats['timeSeries'] = [];

    if (events.length > 0) {
      series = aggregateEventsToVolumeSeries(events, rangeStartMs, rangeEndMs, bucketMs);
    } else {
      const alignedStart = Math.floor(rangeStartMs / bucketMs) * bucketMs;
      const alignedEnd = Math.ceil(rangeEndMs / bucketMs) * bucketMs;
      const buckets = new Map<number, { total: number; cloud: number; local: number }>();
      for (let ts = alignedStart; ts <= alignedEnd; ts += bucketMs) {
        buckets.set(ts, { total: 0, cloud: 0, local: 0 });
      }
      for (const point of tsSeries) {
        if (point.timestamp < alignedStart || point.timestamp > alignedEnd) continue;
        const bucketTs = Math.floor(point.timestamp / bucketMs) * bucketMs;
        const current = buckets.get(bucketTs) || { total: 0, cloud: 0, local: 0 };
        current.total += point.total || 0;
        current.cloud += point.cloud || 0;
        current.local += point.local || 0;
        buckets.set(bucketTs, current);
      }
      series = applyTimeSeriesLabels(
        Array.from(buckets.entries())
          .map(([timestamp, v]) => ({
            timestamp,
            label: '',
            total: v.total,
            cloud: v.cloud,
            local: v.local,
            avgRunSeconds: null,
            avgVram: null,
          }))
          .sort((a, b) => a.timestamp - b.timestamp),
        new Date(alignedStart),
        new Date(alignedEnd),
      );
    }

    return {
      totalLineData: series.map((p) => ({ value: p.total || 0, timestamp: p.timestamp })),
      cloudLineData: series.map((p) => ({ value: p.cloud || 0, timestamp: p.timestamp })),
      localLineData: series.map((p) => ({ value: p.local || 0, timestamp: p.timestamp })),
    };
  });

  readonly totalLineData = computed(() => this.volumeSeries().totalLineData);
  readonly cloudLineData = computed(() => this.volumeSeries().cloudLineData);
  readonly localLineData = computed(() => this.volumeSeries().localLineData);

  // ── Model series ──────────────────────────────────────────────────────────────

  readonly modelSeriesMap = computed<Record<string, Array<{ value: number; timestamp: number }>>>(
    () => {
      const mts = this.stats()?.modelTimeSeries;
      const totalLine = this.totalLineData();
      if (!mts?.length || !totalLine.length) return {};

      const bucketTimestamps = totalLine.map((p) => p.timestamp);
      const bucketSet = new Set(bucketTimestamps);

      const byModel: Record<string, Map<number, number>> = {};
      for (const entry of mts) {
        const key = String(entry.modelId);
        if (!byModel[key]) byModel[key] = new Map();
        const ts = entry.timestamp;
        if (bucketSet.has(ts)) {
          const m = byModel[key];
          m.set(ts, (m.get(ts) || 0) + entry.count);
        } else {
          let closest = bucketTimestamps[0];
          let minDist = Math.abs(ts - closest);
          for (const bt of bucketTimestamps) {
            const dist = Math.abs(ts - bt);
            if (dist < minDist) {
              minDist = dist;
              closest = bt;
            }
          }
          const m = byModel[key];
          m.set(closest, (m.get(closest) || 0) + entry.count);
        }
      }

      const result: Record<string, Array<{ value: number; timestamp: number }>> = {};
      for (const [modelId, bucketMap] of Object.entries(byModel)) {
        result[modelId] = bucketTimestamps.map((ts) => ({
          value: bucketMap.get(ts) || 0,
          timestamp: ts,
        }));
      }
      return result;
    },
  );

  readonly modelLabelById = computed<Record<string, string>>(() => {
    const nameById: Record<string, string> = {};
    for (const m of this.stats()?.modelBreakdown ?? []) {
      nameById[String(m.modelId)] = m.modelName;
    }
    for (const e of this.stats()?.modelTimeSeries ?? []) {
      const key = String(e.modelId);
      if (!(key in nameById)) nameById[key] = e.modelName;
    }
    const nameCount: Record<string, number> = {};
    for (const name of Object.values(nameById)) {
      nameCount[name] = (nameCount[name] || 0) + 1;
    }
    const labels: Record<string, string> = {};
    for (const [id, name] of Object.entries(nameById)) {
      labels[id] = (nameCount[name] || 0) > 1 ? `${name} (${id})` : name;
    }
    return labels;
  });

  readonly modelColors = computed<Record<string, string>>(() => {
    const breakdown = this.stats()?.modelBreakdown ?? [];
    const map: Record<string, string> = {};
    breakdown.forEach((m, idx) => {
      map[String(m.modelId)] = seriesColor(idx);
    });
    Object.keys(this.modelSeriesMap()).forEach((id) => {
      if (!map[id]) map[id] = seriesColor(Object.keys(map).length);
    });
    return map;
  });

  // ── Distribution pie data ─────────────────────────────────────────────────────

  readonly providerPieData = computed(() => {
    const cloudSum = this.cloudLineData().reduce((acc, p) => acc + (p.value || 0), 0);
    const localSum = this.localLineData().reduce((acc, p) => acc + (p.value || 0), 0);
    return [
      { value: cloudSum, color: CHART_ROLE.cloud, text: 'Cloud' },
      { value: localSum, color: CHART_ROLE.local, text: 'Local' },
    ].filter((d) => d.value > 0);
  });

  readonly modelPieData = computed(() => {
    const windowed = Object.entries(this.modelSeriesMap())
      .map(([id, series]) => ({
        id,
        total: series.reduce((acc, p) => acc + (p.value || 0), 0),
      }))
      .filter((m) => m.total > 0)
      .sort((a, b) => b.total - a.total);

    if (windowed.length === 0) {
      return (this.stats()?.modelBreakdown ?? []).map((m) => ({
        value: m.requestCount,
        color: this.modelColors()[String(m.modelId)] || seriesColor(0),
        text: this.modelLabelById()[String(m.modelId)] || m.modelName,
      }));
    }
    return windowed.map((m) => ({
      value: m.total,
      color: this.modelColors()[m.id] || seriesColor(0),
      text: this.modelLabelById()[m.id] || m.id,
    }));
  });

  // ── KPI scalars ───────────────────────────────────────────────────────────────

  readonly totalRequests = computed(() => this.stats()?.totals.requests ?? 0);
  readonly cloudRequests = computed(() => this.stats()?.totals.cloudRequests ?? 0);
  readonly localRequests = computed(() => this.stats()?.totals.localRequests ?? 0);

  // Historic totals over the selected range (items 6): tokens processed and
  // accumulated cloud cost in microcents.
  readonly totalTokens = computed(() => this.stats()?.totals.totalTokens ?? 0);
  readonly cloudCostMicroCents = computed(() => this.stats()?.totals.cloudCostMicroCents ?? 0);

  /** Format a token count for the KPI card on the K/M/B/T scale. */
  formatTokenCount(v: number): string {
    return formatTokenCountValue(v);
  }

  /** Format cloud cost in microcents as USD (the unit litellm prices in). */
  formatCloudCost(microCents: number): string {
    return formatUsd(microCents);
  }

  readonly cloudPct = computed(() => {
    const total = this.totalRequests();
    const cloud = this.cloudRequests();
    return total > 0 ? Math.round((cloud / total) * 100) : 0;
  });

  readonly coldStarts = computed(() => this.stats()?.totals.coldStarts ?? 0);
  readonly warmStarts = computed(() => this.stats()?.totals.warmStarts ?? 0);

  readonly coldPct = computed(() => {
    const cold = this.coldStarts();
    const warm = this.warmStarts();
    const denom = cold + warm;
    return denom > 0 ? Math.round((cold / denom) * 100) : 0;
  });

  readonly coldDenominator = computed(() => this.coldStarts() + this.warmStarts());

  readonly sparkTotal = computed(() =>
    (this.stats()?.timeSeries ?? []).slice(-30).map((p) => p.total || 0),
  );
  readonly sparkCloud = computed(() =>
    (this.stats()?.timeSeries ?? []).slice(-30).map((p) => p.cloud || 0),
  );
  readonly sparkLocal = computed(() =>
    (this.stats()?.timeSeries ?? []).slice(-30).map((p) => p.local || 0),
  );

  // ── Readiness flags ───────────────────────────────────────────────────────────

  /** Statistics have arrived at least once — enough to mount a chart. */
  readonly statsLoaded = computed(() => this.stats() !== null);

  /** …and they describe the range the page currently claims to show. */
  readonly statsReady = computed(() => this.statsLoaded() && !this.statsPending());

  readonly vramReady = computed(() =>
    Object.values(this.vramRawDataByProvider()).some((arr) => arr && arr.length > 0),
  );

  // Deliberately not `!statsReady()`: that is also false while a range change is
  // in flight, so an error arriving then would replace a page full of usable
  // data with the fatal-error screen. Only never having had data is fatal.
  readonly showFatalError = computed(() => this.error() !== null && this.stats() === null);

  // ── Lane KPI helpers ──────────────────────────────────────────────────────────

  readonly totalLanesAcrossProviders = computed(() => {
    let count = 0;
    for (const lanes of Object.values(this.onlineLanesByProvider())) {
      count += Object.keys(lanes).length;
    }
    return count;
  });

  readonly allLanesForKpi = computed(() =>
    Object.values(this.onlineLanesByProvider()).flatMap((p) => Object.values(p)),
  );

  readonly maxLaneVramMb = computed(() =>
    this.allLanesForKpi().reduce((m, l) => Math.max(m, l.effective_vram_mb || 0), 0),
  );

  // ── Status counts ─────────────────────────────────────────────────────────────

  readonly statusCounts = computed<Record<string, number>>(() => this.stats()?.statusCounts ?? {});

  // ── Derived range label ───────────────────────────────────────────────────────

  readonly rangeLabel = computed(() => {
    const cr = this.customRange();
    return cr ? formatRangeLabel(cr) : '';
  });

  // ── Colors exposed to template ────────────────────────────────────────────────

  readonly CHART_ROLE = CHART_ROLE;
  readonly getLaneStateColor = getLaneStateColor;
  readonly STATUS_COLOR = STATUS_COLOR;
  readonly seriesColor = seriesColor;

  // ── Provider-selection auto-ranking effect ────────────────────────────────────

  constructor() {
    effect(() => {
      const providers = this.vramProviders();
      if (!providers.length) {
        this.selectedVramProvider.set(null);
        return;
      }
      const source = this.vramRawDataByProvider();
      const meta = this.vramProviderMetaByName();

      const ranked = [...providers].sort((left, right) => {
        const leftMeta = meta[left];
        const rightMeta = meta[right];
        const leftConnected =
          leftMeta?.connection_state !== 'offline' && leftMeta?.connected !== false;
        const rightConnected =
          rightMeta?.connection_state !== 'offline' && rightMeta?.connected !== false;
        const leftHasSamples = (source[left] || []).length > 0;
        const rightHasSamples = (source[right] || []).length > 0;
        const leftScore = (leftHasSamples ? 2 : 0) + (leftConnected ? 1 : 0);
        const rightScore = (rightHasSamples ? 2 : 0) + (rightConnected ? 1 : 0);
        if (leftScore !== rightScore) return rightScore - leftScore;
        return left.localeCompare(right);
      });

      const current = this.selectedVramProvider();
      if (!current || !providers.includes(current)) {
        this.selectedVramProvider.set(ranked[0]);
      }
    });

    // Position the chart hover tooltip near the cursor, then clamp it inside the
    // viewport so it is always fully visible (critical on narrow mobile screens).
    afterRenderEffect(() => {
      const tt = this.chartTooltip();
      const host = this.chartTooltipEl()?.nativeElement;
      if (!tt || !host) return;

      const margin = 8;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const { width, height } = host.getBoundingClientRect();

      // Prefer right/below the cursor; flip to the other side if it would overflow.
      let left = tt.x + 12;
      if (left + width > vw - margin) left = tt.x - 12 - width;
      left = Math.max(margin, Math.min(left, vw - width - margin));

      let top = tt.y - 8;
      if (top + height > vh - margin) top = tt.y - height + 8;
      top = Math.max(margin, Math.min(top, vh - height - margin));

      host.style.left = `${left}px`;
      host.style.top = `${top}px`;
    });
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────────

  ngOnInit(): void {
    const cfg = this.wsTimelineConfig();
    this.statsWs.connect({
      vramDayOffset: -1, // web path → vram_day = 'all'
      timeline: cfg,
      // Enabled: without the deltas the volume chart is drawn once from the
      // events of the initial load and then never moves again.
      timelineDeltas: true,
      scope: { userId: this.filterUserId(), teamId: this.filterTeamId() },
      handlers: {
        onVramInit: (p) => this.handleVramWsInitV2(p),
        onVramDelta: (p) => this.handleVramWsDeltaV2(p),
        onTimelineInit: (p) => this.handleTimelineInitV2(p),
        onTimelineDelta: (p) => this.handleTimelineDeltaV2(p),
        onStats: (p) => this.handleStatsRefreshV2(p),
        onRequestsData: (p) => this.handleRequestsWsData(p),
      },
    });

    this.nowInterval = setInterval(() => this.nowMs.set(Date.now()), 30_000);
    void this.loadScopeOptions();
  }

  // ── Scope handlers ────────────────────────────────────────────────────────

  setUserFilter(value: string | null): void {
    const id = value ? Number(value) : null;
    const next = Number.isFinite(id as number) ? id : null;
    if (next === this.filterUserId()) return;
    this.filterUserId.set(next);
    this.applyScope();
  }

  /**
   * Pick a team, and the requester list becomes that team's requesters.
   *
   * Not a precondition, though: a handful of people send requests under more
   * than one team, and making the team mandatory would make "everything user X
   * did" unaskable. It is a way to shorten the list, not a gate in front of it.
   */
  setTeamFilter(value: string | null): void {
    const id = value ? Number(value) : null;
    const next = Number.isFinite(id as number) ? id : null;
    if (next === this.filterTeamId()) return;
    this.filterTeamId.set(next);
    this.applyScope();
    void this.loadScopeOptions();
  }

  clearFilter(): void {
    if (!this.filterActive()) return;
    this.filterUserId.set(null);
    this.filterTeamId.set(null);
    this.applyScope();
    void this.loadScopeOptions();
  }

  /**
   * Hand the new scope to the server and blank every range-scoped panel until
   * it answers. Same treatment a range change gets: the numbers on screen
   * describe the previous scope, and leaving them up while the new ones are in
   * flight is how a filter appears not to have worked.
   */
  private applyScope(): void {
    this.markRangeChanged();
    this.statsWs.setScope({ userId: this.filterUserId(), teamId: this.filterTeamId() });
  }

  /**
   * Refill the filter dropdowns for the current range and team.
   *
   * These used to be the platform's user and team inventory, read once. That is
   * a different list from a useful one: it held every account ever created,
   * including the majority that have never sent a request, and a native select
   * has no search box to dig through it with. Now the server answers with what
   * the range actually contains — and, once a team is picked, only that team's
   * requesters.
   *
   * Re-run on a range change as well as a team change, since a narrower window
   * holds fewer of both.
   */
  private async loadScopeOptions(): Promise<void> {
    const cfg = this.wsTimelineConfig();
    const teamId = this.filterTeamId();
    try {
      const options = await this.statisticsService.getScopeOptions(cfg.start, cfg.end, teamId);
      this.feedTeams.set(options.teams ?? []);
      this.feedUsers.set(options.requesters ?? []);

      // The selected requester may not be in the new list — a different team, or
      // a range they were quiet in. Leaving them selected would hold the page on
      // a scope with no data and no visible cause, since the dropdown cannot
      // show a value it has no option for.
      const userId = this.filterUserId();
      if (userId !== null && !this.feedUsers().some((u) => u.id === userId)) {
        this.filterUserId.set(null);
        this.applyScope();
      }
    } catch {
      // A failure leaves the dropdowns as they are, which still describes the
      // scope in force. No reason to bother the operator about it.
    }
  }

  ngOnDestroy(): void {
    this.statsWs.disconnect();
    if (this.nowInterval !== null) {
      clearInterval(this.nowInterval);
      this.nowInterval = null;
    }
  }

  // ── Public actions ────────────────────────────────────────────────────────────

  onRefresh(): void {
    this.refreshing.set(true);
    this.markRangeChanged();
    this.statsWs.reconnect();
  }

  /** Mark every range-scoped panel as loading until the next push resolves it. */
  private markRangeChanged(): void {
    this.statsPending.set(true);
    this.requestsPending.set(true);
  }

  setSelectedVramProvider(name: string | null): void {
    this.selectedVramProvider.set(name);
  }

  /**
   * The user-selected time range in epoch ms — the VRAM-remaining chart
   * windows its (always-live 'all') samples over this global range instead of
   * maintaining its own day offset.
   */
  readonly selectedTimeRangeMs = computed(() => {
    const cfg = this.wsTimelineConfig();
    const cfgEndMs = new Date(cfg.end).getTime();
    // Follow the ticker while the selection is live. wsTimelineConfig only
    // recomputes when the preset, offset or zoom changes, so its end is the
    // instant the range was picked — and the chart drops every sample past its
    // window end, which would leave the curve standing still on an open page.
    const nowMs = this.nowMs();
    return {
      startMs: new Date(cfg.start).getTime(),
      endMs: this.isLiveEnd(cfgEndMs, nowMs) ? Math.max(cfgEndMs, nowMs) : cfgEndMs,
    };
  });

  /**
   * Whether a range end means "up to now" rather than a fixed past instant.
   * Same 120 s tolerance the websocket applies, so the client and the server
   * agree on which selections keep growing.
   */
  private isLiveEnd(endMs: number, nowMs: number): boolean {
    return nowMs - endMs <= 120_000;
  }

  /**
   * The range the request feed pages through.
   *
   * A live selection keeps growing, and the websocket queries it up to its own
   * "now" on every push. So the open end is left empty here for the server to
   * resolve the same way — pinning it to the instant the range was picked would
   * offset the history pages against the live rows above them.
   */
  readonly requestFeedRange = computed(() => {
    const cfg = this.wsTimelineConfig();
    const endMs = new Date(cfg.end).getTime();
    return {
      startIso: cfg.start,
      endIso: this.isLiveEnd(endMs, Date.now()) ? '' : cfg.end,
    };
  });

  /**
   * VRAM samples of the selected provider only. The remaining-VRAM chart sits
   * in the provider-scoped section, so it shows that provider's curve — every
   * other panel in that section is scoped the same way.
   */
  readonly selectedProviderVramData = computed<Record<string, VramV2Sample[]>>(() => {
    const prov = this.selectedVramProvider();
    if (!prov) return {};
    const samples = this.vramRawDataByProvider()[prov];
    return samples ? { [prov]: samples } : {};
  });

  /** True while the selected provider's worker is running a calibration session. */
  readonly selectedProviderCalibrating = computed(() => {
    const prov = this.selectedVramProvider();
    if (!prov) return false;
    return this.vramProviderMetaByName()[prov]?.calibrating === true;
  });

  setCustomRange(range: { start: Date; end: Date }): void {
    this.customRange.set(range);
    this.markRangeChanged();
    this.statsWs.setTimelineRange(this.wsTimelineConfig());
  }

  clearCustomRange(): void {
    this.customRange.set(null);
    this.resetZoomCounter.update((c) => c + 1);
    this.markRangeChanged();
    this.statsWs.setTimelineRange(this.wsTimelineConfig());
  }

  setPreset(p: TimePreset): void {
    this.preset.set(p);
    this.offset.set(0);
    this.clearCustomRange();
    this.statsWs.setTimelineRange(this.wsTimelineConfig());
    // The dropdowns list what the range holds, so a different range is a
    // different list — and possibly one the current selection is not in.
    void this.loadScopeOptions();
  }

  setOffset(o: number): void {
    this.offset.set(o);
    this.clearCustomRange();
    this.statsWs.setTimelineRange(this.wsTimelineConfig());
    void this.loadScopeOptions();
  }

  formatChartValue(v: number): string {
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M req`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(0)}k req`;
    return `${Math.round(v)} req`;
  }

  // ── WS handlers ───────────────────────────────────────────────────────────────

  private handleRequestsWsData(payload: { requests?: RequestItem[] }): void {
    if (payload.requests) {
      this.latestRequests.set(payload.requests);
      this.requestsPending.set(false);
    }
  }

  private handleVramWsInitV2(payload: VramV2Payload): void {
    if (payload.error) {
      this.vramError.set(payload.error);
      return;
    }
    if (payload.providers) {
      this.replaceRawVramSeries(payload.providers as any[]);
      this.vramError.set(null);
      this.isVramLoading.set(false);
    }
  }

  private handleVramWsDeltaV2(payload: VramV2Payload): void {
    if (payload.error) {
      this.vramError.set(payload.error);
      return;
    }
    if (!payload.providers || payload.providers.length === 0) return;
    this.appendRawVramSeries(payload.providers as any[]);
    this.vramError.set(null);
    this.isVramLoading.set(false);
  }

  private handleTimelineInitV2(payload: TimelineInitPayload): void {
    if (payload.error) {
      this.error.set(payload.error);
      this.refreshing.set(false);
      this.statsPending.set(false);
      this.hasResolvedStats = true;
      return;
    }
    if (!payload.stats) {
      this.error.set('No statistics data available.');
      this.refreshing.set(false);
      this.statsPending.set(false);
      this.hasResolvedStats = true;
      return;
    }

    const cfg = this.wsTimelineConfig();
    const rangeStart = payload.range?.start ? new Date(payload.range.start) : new Date(cfg.start);
    const rangeEnd = payload.range?.end ? new Date(payload.range.end) : new Date(cfg.end);
    const bucketMs = (payload.bucketSeconds || 60) * 1000;

    this.timelineRangeMs = {
      startMs: rangeStart.getTime(),
      endMs: rangeEnd.getTime(),
      bucketMs,
    };

    this.replaceTimelineEvents(payload.events || []);

    const labeled = applyTimeSeriesLabels(payload.stats.timeSeries || [], rangeStart, rangeEnd);
    this.stats.set({ ...payload.stats, timeSeries: labeled });
    this.error.set(null);
    this.refreshing.set(false);
    this.statsPending.set(false);
    this.hasResolvedStats = true;
  }

  /**
   * Recomputed aggregates for the range the page already shows.
   *
   * Same payload as `timeline_init` without the event list, so it replaces the
   * totals, the status counts and the server-side buckets without touching the
   * events the volume chart is drawn from — those arrive as deltas.
   */
  private handleStatsRefreshV2(payload: TimelineInitPayload): void {
    if (payload.error || !payload.stats) return;
    // A range change is in flight. The server pushes aggregates from its own
    // timer, so one computed for the range we just left can still be on the
    // wire — taking it would put the previous range's numbers back on screen
    // under the new period, which is the exact thing `statsPending` prevents.
    // `timeline_init` is what answers a range change.
    if (this.statsPending()) return;

    const cfg = this.wsTimelineConfig();
    const rangeStart = payload.range?.start ? new Date(payload.range.start) : new Date(cfg.start);
    const rangeEnd = payload.range?.end ? new Date(payload.range.end) : new Date(cfg.end);
    // A live range keeps growing, and the server advances the end with it.
    this.timelineRangeMs = {
      startMs: rangeStart.getTime(),
      endMs: rangeEnd.getTime(),
      bucketMs: (payload.bucketSeconds || 60) * 1000,
    };

    const labeled = applyTimeSeriesLabels(payload.stats.timeSeries || [], rangeStart, rangeEnd);
    this.stats.set({ ...payload.stats, timeSeries: labeled });
  }

  /**
   * Newly enqueued requests, appended to the event list the volume chart
   * re-buckets. Without this the chart would sit still while the counters
   * beside it moved on every aggregate push.
   */
  private handleTimelineDeltaV2(payload: TimelineDeltaPayload): void {
    if (!payload.events?.length) return;
    // Same race as the aggregate push: a delta still in flight belongs to the
    // range being left. `timeline_init` replaces the whole event list anyway.
    if (this.statsPending()) return;
    // Range first: `timelineRangeMs` is a plain field, so the series only picks
    // a new end up when a signal it also reads changes. Appending the events is
    // that signal — do it second or the chart trails the data by one delta.
    if (payload.range?.end) {
      const endMs = new Date(payload.range.end).getTime();
      if (Number.isFinite(endMs) && this.timelineRangeMs) {
        this.timelineRangeMs = { ...this.timelineRangeMs, endMs };
      }
    }
    this.appendTimelineEvents(payload.events);
  }

  // ── Raw-series updaters ───────────────────────────────────────────────────────

  private replaceRawVramSeries(providers: any[]): void {
    const next: Record<string, VramV2Sample[]> = {};
    const nextMeta: Record<string, VramProviderMeta> = {};
    const nextDevices: Record<string, DeviceInfo[]> = {};

    for (const provider of providers || []) {
      const sortedSamples = (provider.data || [])
        .filter((s: any) => s?.timestamp)
        .sort(
          (a: any, b: any) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
        );
      const samples =
        sortedSamples.length > RAW_VRAM_SAMPLE_CAP
          ? sortedSamples.slice(sortedSamples.length - RAW_VRAM_SAMPLE_CAP)
          : sortedSamples;
      next[provider.name] = samples;
      nextMeta[provider.name] = {
        provider_id: provider.provider_id,
        connected: provider.connected,
        connection_state: provider.connection_state,
        provider_type: provider.provider_type,
        runtime_modes: provider.runtime_modes,
        transport_connected: provider.transport_connected,
        last_heartbeat: provider.last_heartbeat,
        calibrating: Boolean(provider.calibrating),
      };
      if (Array.isArray(provider.devices) && provider.devices.length) {
        nextDevices[provider.name] = provider.devices;
      }
    }

    this.vramRawDataByProvider.set(next);
    this.vramProviderMetaByName.set(nextMeta);
    this.devicesByProvider.set(nextDevices);
  }

  private appendRawVramSeries(providers: any[]): void {
    if (!providers || providers.length === 0) return;

    // Update meta
    const prevMeta = this.vramProviderMetaByName();
    let nextMeta = prevMeta;
    for (const provider of providers) {
      const meta: VramProviderMeta = {
        provider_id: provider.provider_id,
        connected: provider.connected,
        connection_state: provider.connection_state,
        provider_type: provider.provider_type,
        runtime_modes: provider.runtime_modes,
        transport_connected: provider.transport_connected,
        last_heartbeat: provider.last_heartbeat,
        calibrating: Boolean(provider.calibrating),
      };
      const current = prevMeta[provider.name];
      const same =
        current?.provider_id === meta.provider_id &&
        current?.connected === meta.connected &&
        current?.connection_state === meta.connection_state &&
        current?.provider_type === meta.provider_type &&
        JSON.stringify(current?.runtime_modes || []) === JSON.stringify(meta.runtime_modes || []) &&
        current?.transport_connected === meta.transport_connected &&
        current?.last_heartbeat === meta.last_heartbeat &&
        Boolean(current?.calibrating) === meta.calibrating;
      if (!same) {
        if (nextMeta === prevMeta) nextMeta = { ...prevMeta };
        nextMeta[provider.name] = meta;
      }
    }
    if (nextMeta !== prevMeta) this.vramProviderMetaByName.set(nextMeta);

    // Update devices
    const prevDevices = this.devicesByProvider();
    let nextDevices = prevDevices;
    for (const provider of providers) {
      if (Array.isArray(provider.devices) && provider.devices.length) {
        if (nextDevices === prevDevices) nextDevices = { ...prevDevices };
        nextDevices[provider.name] = provider.devices;
      }
    }
    if (nextDevices !== prevDevices) this.devicesByProvider.set(nextDevices);

    // Merge raw samples
    const prev = this.vramRawDataByProvider();
    let next = prev;
    for (const provider of providers) {
      const incoming = (provider.data || []).filter((s: any) => s?.timestamp);
      if (!incoming.length) continue;
      const current = prev[provider.name] || [];
      const byKey = new Map<string, any>();
      for (const sample of current) {
        byKey.set(String(sample.snapshot_id ?? sample.timestamp ?? ''), sample);
      }
      for (const sample of incoming) {
        byKey.set(String(sample.snapshot_id ?? sample.timestamp ?? ''), sample);
      }
      const merged = Array.from(byKey.values()).sort(
        (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
      );
      const capped =
        merged.length > RAW_VRAM_SAMPLE_CAP
          ? merged.slice(merged.length - RAW_VRAM_SAMPLE_CAP)
          : merged;
      if (next === prev) next = { ...prev };
      next[provider.name] = capped;
    }
    if (next !== prev) this.vramRawDataByProvider.set(next);
  }

  /** Request ids already in `timelineEvents`, so a delta can dedupe in O(1). */
  private readonly knownEventIds = new Set<string>();

  private replaceTimelineEvents(events: TimelineEnqueueEvent[]): void {
    const nextMap = new Map<string, TimelineEnqueueEvent>();
    for (const event of events || []) {
      if (!event?.request_id || !Number.isFinite(Number(event.timestamp_ms))) continue;
      nextMap.set(event.request_id, event);
    }
    const merged = Array.from(nextMap.values()).sort((a, b) => a.timestamp_ms - b.timestamp_ms);
    this.knownEventIds.clear();
    for (const event of merged) this.knownEventIds.add(event.request_id);
    this.timelineEvents.set(merged);
  }

  /**
   * Append delta events to the list the volume chart re-buckets.
   *
   * Appended rather than merged and re-sorted: the server hands out deltas from
   * a cursor that only ever moves forward, starting at the end of the initially
   * loaded range, so every delta event is newer than everything already here.
   * That matters at this cadence — re-sorting a list that can hold 200k events
   * every two seconds would be felt on the UI thread.
   *
   * Capped, dropping the oldest: a long session on a busy range would otherwise
   * grow without bound. Losing the oldest thins out the left edge of the chart
   * rather than its live end, which is the side being watched, and
   * `stats.timeSeries` — refreshed alongside — still covers the whole range for
   * anyone reading totals.
   */
  private appendTimelineEvents(events: TimelineEnqueueEvent[]): void {
    const fresh: TimelineEnqueueEvent[] = [];
    for (const event of events) {
      if (!event?.request_id || !Number.isFinite(Number(event.timestamp_ms))) continue;
      if (this.knownEventIds.has(event.request_id)) continue;
      this.knownEventIds.add(event.request_id);
      fresh.push(event);
    }
    if (fresh.length === 0) return;

    const current = this.timelineEvents();
    let next = [...current, ...fresh];
    if (next.length > TIMELINE_EVENT_CAP) {
      const dropped = next.slice(0, next.length - TIMELINE_EVENT_CAP);
      for (const event of dropped) this.knownEventIds.delete(event.request_id);
      next = next.slice(next.length - TIMELINE_EVENT_CAP);
    }
    this.timelineEvents.set(next);
  }

  // ── Helpers ───────────────────────────────────────────────────────────────────

  private _isProviderOnline(name: string): boolean {
    const m = this.vramProviderMetaByName()[name];
    return m?.connection_state !== 'offline' && m?.connected !== false;
  }

  isProviderOnline = (name: string): boolean => this._isProviderOnline(name);

  /** Expose lane bar height for template micro-bar in Active Lanes KPI. */
  laneBarHeight(lane: LaneSignalData): number {
    const max = this.maxLaneVramMb();
    const ratio = max > 0 ? (lane.effective_vram_mb || 0) / max : 0;
    return Math.max(4, Math.round(ratio * 28));
  }

  laneBarColor(lane: LaneSignalData): string {
    return getLaneStateColor(lane.runtime_state);
  }

  get avgRunSeconds(): number {
    return this.stats()?.totals.avgRunSeconds ?? 0;
  }

  get avgQueueSeconds(): number {
    return this.stats()?.totals.avgQueueSeconds ?? 0;
  }
}
