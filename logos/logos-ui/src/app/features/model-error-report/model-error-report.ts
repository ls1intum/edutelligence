import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { NgClass } from '@angular/common';
import {
  CdkVirtualScrollViewport,
  ScrollingModule,
} from '@angular/cdk/scrolling';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

import { ModelManagementService } from '../../core/services/model-management.service';
import { Model } from '../../shared/models/model.model';
import {
  GuideLlmStatusDistributionSummary,
  ModelBenchmarkPair,
  ModelBenchmarkRun,
  ModelProviderBenchmark,
} from '../../shared/models/provider.model';

import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import {
  benchmarkConfigurationRows,
  servingCommand,
} from './benchmark-configuration';


// ==========================================================================
// Types
// ==========================================================================

type ModelErrorTab =
  | 'error_report'
  | 'complete_logs'
  | 'performance';

type CalibrationStatus =
  | 'success'
  | 'failure'
  | 'unknown';

interface ErrorScope {
  readonly type: 'global' | 'node';
  readonly nodes?: readonly string[];
}

interface ChecklistItem {
  readonly name: string;
  readonly status: 'success' | 'failure';
  readonly errorMessage?: string;
  readonly errorDetail?: string;
  readonly scope?: ErrorScope;
  readonly reasonKind?: AuthoritativeReasonKind;
  readonly reasonCode?: string;
  // Literal raw-log substring for openNodeLog's scroll-to-line search —
  // distinct from errorMessage, which is a polished display label that
  // won't itself appear verbatim in the log. Falls back to errorMessage
  // only when no better anchor exists (see openNodeLog call site).
  readonly logAnchor?: string;
}


type AuthoritativeReasonKind = 'unsupported' | 'node_unhealthy' | 'observed';

interface AuthoritativeReason {
  readonly kind: AuthoritativeReasonKind;
  readonly code: string;
  readonly label: string;
  readonly description: string;
  readonly domain?: string;
  readonly needle?: string;
}

interface CalibrationStageResult {
  readonly name: string;
  readonly status: CalibrationStatus;
  readonly errorMessage?: string;
  readonly errorDetail?: string;
  readonly reasonKind?: AuthoritativeReasonKind;
  readonly reasonCode?: string;
  readonly logAnchor?: string;
}

interface CalibrationProbeResult {
  readonly probe: number;
  readonly status: CalibrationStatus;
  readonly stages: readonly CalibrationStageResult[];
  readonly errorMessage?: string;
  readonly errorDetail?: string;
  readonly reasonKind?: AuthoritativeReasonKind;
  readonly reasonCode?: string;
  readonly logAnchor?: string;
}

interface CalibrationError {
  readonly summary: string;
  readonly detail: string;
}

interface NodeCalibrationResult {
  readonly providerId: number;
  readonly node: string;
  readonly status: CalibrationStatus;
  readonly attempts: number;
  readonly probes: readonly CalibrationProbeResult[];
}

interface ModelLog {
  readonly providerId: number;
  readonly node: string;
  readonly modelName: string;
}

interface BackendStageResult {
  readonly name: string;
  readonly status: CalibrationStatus;
  readonly reason_kind?: AuthoritativeReasonKind | null;
  readonly reason_code?: string | null;
  readonly generic_error_message?: string | null;
  readonly generic_error_detail?: string | null;
  readonly log_anchor?: string | null;
}

interface BackendCalibrationLog {
  readonly provider_id: number;
  readonly provider_name: string;
  readonly success: boolean;
  readonly probe_command: string | null;
  readonly error: string | null;
  readonly log_text: string | null;
  readonly unsupported_reason: string | null;
  readonly node_unhealthy_reason: string | null;
  readonly observed_reason: string | null;
  readonly stages: readonly BackendStageResult[] | null;
  readonly recorded_at: string | null;
  readonly updated_at: string;
}

interface BenchmarkGroup {
  readonly modelProviderId: number;
  readonly benchmarks: readonly ModelProviderBenchmark[];
  readonly selected: ModelProviderBenchmark;
}


// ==========================================================================
// Worker Reason Codes
//
// Mirrors logos-workernode/logos_worker_node/calibration.py
// _FATAL_LOAD_ERROR_PATTERNS / _NODE_LEVEL_TRANSIENT_PATTERNS. Keep in
// sync by hand when patterns are added/changed worker-side — there is no
// shared codegen between Python and TS.
// ==========================================================================

// Mirrors calibration.py's _DOMAIN_* ids — the deployment failure domains
// that ARE the stage checklist now (see CALIBRATION_DOMAINS below). Keep
// in sync by hand; no shared codegen between Python and TS.
const DOMAIN_NODE_PREFLIGHT = 'node_preflight';
const DOMAIN_MODEL_RESOLUTION = 'model_resolution';
const DOMAIN_ENGINE_INIT = 'engine_init';
const DOMAIN_MULTI_GPU_COORDINATION = 'multi_gpu_coordination';
const DOMAIN_WEIGHT_LOADING = 'weight_loading';
const DOMAIN_KV_CACHE_FIT = 'kv_cache_fit';
const DOMAIN_SERVER_START = 'server_start';

interface ReasonDescription {
  readonly label: string;
  readonly description: string;
  // Which failure domain (see above) this reason attaches to when the UI
  // has to classify a raw log itself (backend-supplied `stages` already
  // carry their own attachment and ignore this). undefined = no single
  // deterministic point — resolved positionally instead, same convention
  // as calibration.py's Pattern.domain=None.
  readonly domain?: string;
  // The pattern's literal needle (mirrors calibration.py's
  // Pattern.needle) — guaranteed to exist verbatim in the raw log,
  // unlike `label`/`description` above which are polished for display.
  // Used ONLY to scroll to and highlight the matching log line (see
  // openNodeLog) when this reason came from the regex fallback path —
  // backend-supplied stages carry their own log_anchor instead.
  readonly needle?: string;
  // For a reason that can occur at more than one point in the sequence
  // (domain=undefined, resolved positionally — e.g. cuda-oom can be
  // "weights don't fit" OR "KV cache doesn't fit", which are different
  // situations needing different fixes), override label/description
  // per the domain it actually resolved to. Keyed by domain id (see
  // DOMAIN_* above). A domain with no entry here falls back to the
  // generic label/description — this is deliberately sparse, only for
  // reasons where the phase changes what ops should actually do.
  readonly domainOverrides?: Record<string, { label: string; description: string }>;
}

const UNSUPPORTED_REASON_DESCRIPTIONS: Record<string, ReasonDescription> = {
  'invalid-repo-id': {
    label: 'Invalid repository ID',
    description:
      'vLLM cannot resolve the model name to a Hugging Face ' +
      'repository or a local directory with config.json.',
    domain: DOMAIN_MODEL_RESOLUTION,
    needle: 'Invalid repository ID or local directory specified',
  },
  'gated-repo-no-token': {
    label: 'Gated repository, no HF token',
    description:
      'Hugging Face flags this repository as gated and the worker ' +
      'has no (or an insufficient) HF token.',
    domain: DOMAIN_MODEL_RESOLUTION,
    needle: 'Cannot access gated repo',
  },
  'unsupported-architecture': {
    label: 'Unsupported architecture',
    description:
      'The installed vLLM build does not implement this model\'s ' +
      'architecture.',
    domain: DOMAIN_ENGINE_INIT,
    needle: 'does not recognize this architecture',
  },
  'requires-trust-remote-code': {
    label: 'Requires trust_remote_code',
    description:
      'This repository ships custom modeling code and requires ' +
      'trust_remote_code=True, which is not auto-enabled.',
    domain: DOMAIN_MODEL_RESOLUTION,
    needle: 'trust_remote_code=True',
  },
  'unsupported-quantization': {
    label: 'Unsupported quantization method',
    description:
      'The installed vLLM build does not support this model\'s ' +
      'quantization method on this hardware.',
    domain: DOMAIN_ENGINE_INIT,
    needle: 'is not supported for quantization method',
  },
};

const NODE_UNHEALTHY_REASON_DESCRIPTIONS: Record<string, ReasonDescription> = {
  'filesystem-eio': {
    label: 'Filesystem I/O error',
    description:
      'Filesystem reads are failing with EIO. The backing storage ' +
      'on this node is degraded or disconnected.',
    // Can hit at any disk access — resolved positionally (domain omitted).
    needle: 'Input/output error',
  },
  'filesystem-readonly': {
    label: 'Filesystem remounted read-only',
    description:
      'The kernel remounted this node\'s filesystem read-only ' +
      'after I/O errors.',
    // Same reasoning as filesystem-eio above.
    needle: 'Read-only file system',
  },
  'disk-space-exhausted': {
    label: 'Disk space exhausted',
    description: 'The node\'s disk is full — nothing can be written.',
    // Same reasoning as filesystem-eio above.
    needle: 'No space left on device',
  },
  'cuda-device-not-detected': {
    label: 'No GPU detected',
    description: 'No CUDA-capable device is visible to vLLM on this node.',
    domain: DOMAIN_NODE_PREFLIGHT,
    needle: 'no CUDA-capable device is detected',
  },
  'cuda-driver-runtime-mismatch': {
    label: 'CUDA driver/runtime mismatch',
    description:
      'The installed NVIDIA driver is older than the CUDA runtime ' +
      'vLLM requires on this node.',
    domain: DOMAIN_NODE_PREFLIGHT,
    needle: 'CUDA driver version is insufficient for CUDA runtime version',
  },
};

const OBSERVED_REASON_DESCRIPTIONS: Record<string, ReasonDescription> = {
  'cuda-oom': {
    label: 'CUDA out of memory (observed)',
    description:
      'The GPU ran out of memory on the last failing probe. Non-blocking ' +
      '— the kv-cache search retries with a smaller budget automatically.',
    // Can hit during weight loading OR kv-cache reservation OR warmup —
    // resolved positionally (domain omitted). These are operationally
    // different situations, so the resolved stage gets a tailored
    // description instead of the generic text above (see
    // domainOverrides / lookupReason's resolvedDomainId param).
    needle: 'CUDA out of memory',
    domainOverrides: {
      [DOMAIN_WEIGHT_LOADING]: {
        label: 'Model weights too large for GPU',
        description:
          'The model\'s weights alone exceeded available GPU memory ' +
          'while loading — before any KV cache was even reserved. ' +
          'Shrinking the KV-cache budget will NOT fix this; the model ' +
          'needs a smaller quantization, more tensor-parallel GPUs, or ' +
          'more VRAM.',
      },
      [DOMAIN_KV_CACHE_FIT]: {
        label: 'KV-cache budget exceeds free memory',
        description:
          'The model itself loaded successfully, but the requested ' +
          'KV-cache size didn\'t fit in the remaining GPU memory. This ' +
          'is the expected, self-correcting case — the calibration ' +
          'search automatically retries with a smaller KV-cache budget.',
      },
      [DOMAIN_SERVER_START]: {
        label: 'Out of memory during CUDA graph warmup',
        description:
          'Both the model weights and KV cache fit, but the GPU ran ' +
          'out of memory during CUDA graph capture/warmup — often a ' +
          'sign the memory headroom is borderline. If this persists, ' +
          'consider enabling eager mode (--enforce-eager) or reducing ' +
          'concurrency.',
      },
    },
  },
  'cuda-runtime-error': {
    label: 'CUDA runtime error (observed)',
    description:
      'A CUDA runtime error occurred on the last failing probe (not ' +
      'out-of-memory — see the full log for specifics, e.g. "unspecified ' +
      'launch failure"). Often a driver, kernel, or multi-GPU sync crash.',
    // Can hit at essentially any point CUDA kernels run — resolved
    // positionally (domain omitted), same as cuda-oom.
    needle: 'CUDA error:',
  },
  'hf-network-timeout': {
    label: 'Hugging Face network timeout (observed)',
    description:
      'A Hugging Face Hub request timed out on the last failing probe. ' +
      'Usually transient.',
    domain: DOMAIN_MODEL_RESOLUTION,
    needle: 'Read timed out',
  },
  'hf-rate-limited': {
    label: 'Hugging Face rate limited (observed)',
    description:
      'Hugging Face Hub rate-limited the download on the last failing ' +
      'probe. Usually transient.',
    domain: DOMAIN_MODEL_RESOLUTION,
    needle: 'Too Many Requests',
  },
  'nccl-handshake-failure': {
    label: 'NCCL handshake failure (observed)',
    description:
      'NCCL failed to establish communication between vLLM ranks on ' +
      'the last failing probe. Often transient.',
    domain: DOMAIN_MULTI_GPU_COORDINATION,
    needle: 'NCCL error',
  },
  'port-in-use': {
    label: 'Port already in use (observed)',
    description:
      'The port vLLM tried to bind was still held by a prior process ' +
      'on the last failing probe. Usually resolves on retry.',
    domain: DOMAIN_SERVER_START,
    needle: 'Address already in use',
  },
};

function lookupReason(
  kind: AuthoritativeReasonKind,
  code: string,
  resolvedDomainId?: string
): ReasonDescription {
  const table =
    kind === 'unsupported'
      ? UNSUPPORTED_REASON_DESCRIPTIONS
      : kind === 'node_unhealthy'
      ? NODE_UNHEALTHY_REASON_DESCRIPTIONS
      : OBSERVED_REASON_DESCRIPTIONS;

  const base = table[code] ?? {
    label: code,
    description:
      `Worker reported reason code "${code}", which the UI does ` +
      'not yet recognize (frontend out of date with calibration.py?).',
  };

  const override = resolvedDomainId
    ? base.domainOverrides?.[resolvedDomainId]
    : undefined;

  return override ? { ...base, ...override } : base;
}

// ==========================================================================
// Calibration Domains
//
// Mirrors calibration.py's _CALIBRATION_DOMAINS — 7 failure-domain
// checklist rows, replacing the old flat log-line-driven stage list.
// Each domain's completion is proven by ANY of its completionPatterns
// matching; a domain with none (nodePreflight, multiGpuCoordination) is
// inferred complete once a LATER domain's pattern matches instead. See
// calibration.py for the full design rationale — this is the regex
// FALLBACK path only (successful nodes, legacy data, a worker not yet
// upgraded); a worker-supplied `stages` array is always preferred when
// present (see buildProbeResultFromBackendStages).
//
// One difference from the Python source of truth: `requires: 'multi_gpu'`
// can't be evaluated here (the frontend has no per-attempt
// tensor_parallel_size), so multiGpuCoordination is always included in
// this fallback path — for a real tp=1 deployment it will typically just
// show as an (inferred) success, which is a harmless overstatement, not
// a wrong failure.
//
// Extending this: add a CalibrationDomain entry here AND a matching
// domain= tag on the relevant entry in UNSUPPORTED_REASON_DESCRIPTIONS /
// NODE_UNHEALTHY_REASON_DESCRIPTIONS / OBSERVED_REASON_DESCRIPTIONS above
// — same two-step process as calibration.py.
// ==========================================================================

interface CalibrationDomainDef {
  readonly id: string;
  readonly label: string;
  readonly completionPatterns: readonly RegExp[];
}

const CALIBRATION_DOMAINS: readonly CalibrationDomainDef[] = [
  {
    id: DOMAIN_NODE_PREFLIGHT,
    label: 'Node Preflight',
    completionPatterns: [],
  },
  {
    id: DOMAIN_MODEL_RESOLUTION,
    label: 'Model Resolution & Download',
    completionPatterns: [/non-default args:/],
  },
  {
    id: DOMAIN_ENGINE_INIT,
    label: 'Engine Initialization',
    completionPatterns: [/Initializing a V1 LLM engine/],
  },
  {
    id: DOMAIN_MULTI_GPU_COORDINATION,
    label: 'Multi-GPU Coordination',
    completionPatterns: [],
  },
  {
    id: DOMAIN_WEIGHT_LOADING,
    label: 'Weight Loading',
    completionPatterns: [/Model loading took/],
  },
  {
    id: DOMAIN_KV_CACHE_FIT,
    label: 'KV-Cache Memory Fit',
    completionPatterns: [/reserved .* memory for KV Cache/],
  },
  {
    id: DOMAIN_SERVER_START,
    label: 'Server Start',
    completionPatterns: [
      /Starting vLLM server on/,
      /Application startup complete\./,
      /"GET \/health HTTP\/1\.1"\s+200\s+OK/,
    ],
  },
];

// Lines confirmed, against real production logs, to be benign vLLM
// fallback/informational messages that happen to be tagged at ERROR log
// level — NOT failures. Mirrors
// _GENERIC_CALIBRATION_ERROR_IGNORE_NEEDLES in calibration.py. Without
// this, getCalibrationError (which takes the FIRST line matching its
// patterns) picks these over the actual root cause further down the log.
const GENERIC_CALIBRATION_ERROR_IGNORE_NEEDLES: readonly string[] = [
  // FA2 requires compute capability >= 8; vLLM logs this at ERROR level
  // then gracefully falls back to TRITON_ATTN/FLEX_ATTENTION and
  // continues — confirmed benign against two real logs, one of which
  // completed successfully with this exact line present (2026-09-07).
  'Cannot use FA version 2 is not supported',
  // vLLM's optional-dependency soft-check (_has_module in
  // vllm/utils/import_utils.py) logs a full WARNING-level traceback for
  // ANY optional module that fails to import (numba confirmed benign in
  // a real log where calibration succeeded, 2026-09-07) — by design it
  // never fails calibration. vLLM tags every physical line of the dump
  // with the same "[import_utils.py:<N>]" source location, so matching
  // that prefix (not a version-specific line number) covers the WHOLE
  // block, including lines deep in the trace (e.g. "raise ImportError")
  // that a narrower, opening-line-only needle would miss.
  '[import_utils.py:',
];

// Deliberately tight (not e.g. 5+): a wide window risks suppressing a
// genuinely unrelated real error that happens to occur near a benign
// marker. 1 is the minimum that covers both confirmed cases above — the
// marker is either ON the matched line itself (FA2) or exactly one line
// before it (numba's "Traceback (most recent call last):" immediately
// follows its "failed to import" line).
const GENERIC_CALIBRATION_ERROR_IGNORE_WINDOW = 1;


@Component({
  selector: 'app-model-error-report',
  standalone: true,

  imports: [
    RouterLink,
    NgClass,
    ScrollingModule,
    ErrorMessageComponent,
  ],

  templateUrl: './model-error-report.html',
  styleUrls: [
    './model-error-report.scss',
    './model-performance-details.scss',
  ],

  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModelErrorReport implements OnInit, OnDestroy {

  // ==========================================================================
  // Dependencies
  // ==========================================================================

  private readonly route = inject(ActivatedRoute);
  private readonly modelService = inject(ModelManagementService);
  private readonly http = inject(HttpClient);


  // ==========================================================================
  // Component State
  // ==========================================================================

  readonly model = signal<Model | null>(null);
  readonly modelId = signal<number | null>(null);

  readonly loading = signal(true);
  readonly loadError = signal(false);

  readonly activeTab = signal<ModelErrorTab>('error_report');

  private readonly expandedErrors = signal<ReadonlySet<string>>(new Set());

  readonly selectedLogProviderId = signal<number | null>(null);

  private readonly logCopyResult =
    signal<{ providerId: number; ok: boolean } | null>(null);
  private logCopiedResetTimer: ReturnType<typeof setTimeout> | null = null;

  readonly logCopied = computed(() => {
    const result = this.logCopyResult();
    return result !== null && result.ok && result.providerId === this.selectedLogProviderId();
  });

  readonly logCopyFailed = computed(() => {
    const result = this.logCopyResult();
    return result !== null && !result.ok && result.providerId === this.selectedLogProviderId();
  });

  private readonly rawLogsByProviderId =
    signal<ReadonlyMap<number, string>>(new Map());

  private readonly modelLogs =
    signal<readonly ModelLog[]>([]);

  private readonly calibrationResults =
    signal<readonly NodeCalibrationResult[]>([]);

  readonly highlightedError =
    signal<string | undefined>(undefined);

  readonly highlightedErrorNode =
    signal<number | null>(null);

  readonly performance = signal<readonly ModelProviderBenchmark[]>([]);
  readonly benchmarkPairs = signal<readonly ModelBenchmarkPair[]>([]);
  readonly benchmarkRuns = signal<readonly ModelBenchmarkRun[]>([]);
  readonly performanceLoading = signal(false);
  readonly performanceError = signal(false);
  readonly benchmarkStartingPairId = signal<number | null>(null);
  readonly benchmarkCancellingJobId = signal<number | null>(null);
  readonly benchmarkStartError = signal<string | null>(null);
  readonly benchmarkSampleSize = signal(5);
  readonly benchmarkSampleLabel = computed(
    () => this.formatSampleCount(this.benchmarkSampleSize()),
  );
  readonly benchmarkSampleTicks = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100] as const;
  readonly benchmarkSampleProgress = computed(
    () => `${((this.benchmarkSampleSize() - 1) / 99) * 100}%`,
  );
  private readonly selectedBenchmarkIds = signal<ReadonlyMap<number, number>>(new Map());
  readonly benchmarkDeletingId = signal<number | null>(null);
  readonly benchmarkDeleteError = signal<string | null>(null);
  readonly benchmarkGroups = computed<readonly BenchmarkGroup[]>(() => {
    const grouped = new Map<number, ModelProviderBenchmark[]>();
    for (const benchmark of this.performance()) {
      const benchmarks = grouped.get(benchmark.model_provider_id) ?? [];
      benchmarks.push(benchmark);
      grouped.set(benchmark.model_provider_id, benchmarks);
    }
    const selectedIds = this.selectedBenchmarkIds();
    return [...grouped.entries()].map(([modelProviderId, benchmarks]) => ({
      modelProviderId,
      benchmarks,
      selected: benchmarks.find(benchmark => benchmark.id === selectedIds.get(modelProviderId)) ?? benchmarks[0]!,
    }));
  });
  private performancePollTimer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;

  // ==========================================================================
  // Tabs
  // ==========================================================================

  readonly tabs: readonly ModelErrorTab[] = [
    'error_report',
    'complete_logs',
    'performance',
  ];

  readonly tabLabel: Record<ModelErrorTab, string> = {
    error_report: 'Error Report',
    complete_logs: 'Complete Logs',
    performance: 'Performance',
  };

  readonly hasAnyLogText = computed(() => {
    return [...this.rawLogsByProviderId().values()].some(text => text.length > 0);
  });

  readonly visibleTabs =
    computed<readonly ModelErrorTab[]>(() => this.tabs);


  // ==========================================================================
  // Logs
  // ==========================================================================

  readonly availableLogs = computed(() => {
    const currentModel = this.model();

    if (!currentModel) {
      return [];
    }

    return this.modelLogs().filter(
      log => log.modelName === currentModel.name
    );
  });

  readonly selectedLog = computed(() => {
    const logs = this.availableLogs();

    if (!logs.length) {
      return null;
    }

    const selectedProviderId = this.selectedLogProviderId();

    return (
      logs.find(log => log.providerId === selectedProviderId) ??
      logs[0]
    );
  });

  readonly completeLog = computed(() => {
    const providerId = this.selectedLog()?.providerId;
    if (providerId == null) {
      return '';
    }
    return this.rawLogsByProviderId().get(providerId) ?? '';
  });

  readonly logLines = computed(() =>
    this.completeLog().split('\n')
  );

  readonly highlightedLogLineIndex = computed(() => {
    const error = this.highlightedError();
    const errorProviderId = this.highlightedErrorNode();
    const selectedProviderId = this.selectedLogProviderId();

    if (!error || errorProviderId == null || errorProviderId !== selectedProviderId) {
      return -1;
    }

    return this.logLines().findIndex(line => line.includes(error));
  });

  readonly logViewport =
    viewChild(CdkVirtualScrollViewport);

  readonly hasCompleteLogs = computed(() => {
    return this.availableLogs().length > 0;
  });

  readonly hasParseableCalibrationData = computed(() => {
    return this.calibrationResults().some(result => result.attempts > 0);
  });


  // ==========================================================================
  // Calibration
  // ==========================================================================

  readonly calibrationResult =
    computed<NodeCalibrationResult | null>(() => {
      const selectedLog = this.selectedLog();

      if (!selectedLog) {
        return null;
      }

      return (
        this.calibrationResults().find(
          result => result.providerId === selectedLog.providerId
        ) ?? null
      );
    });


  // ==========================================================================
  // Checklist Data
  // ==========================================================================

  // Flat list of failure-domain checklist rows (see CALIBRATION_DOMAINS) —
  // no grouping layer above this; each domain is its own top-level row.
  readonly checklistItems =
    computed<readonly ChecklistItem[]>(() => {
      if (!this.model()) {
        return [];
      }

      return this.getCalibrationChecklistItems();
    });


  // ==========================================================================
  // Lifecycle
  // ==========================================================================

  async ngOnInit(): Promise<void> {
    const id = Number(
      this.route.snapshot.paramMap.get('id')
    );

    this.modelId.set(id);

    await this.fetchModel(id);
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.clearPerformancePoll();
    if (this.logCopiedResetTimer !== null) {
      clearTimeout(this.logCopiedResetTimer);
    }
  }


  // ==========================================================================
  // Initial Data Loading
  // ==========================================================================

  async fetchModel(id: number): Promise<void> {
    this.loading.set(true);
    this.loadError.set(false);

    try {
      const models =
        await this.modelService.getModels();

      const foundModel = models.find(
        model => model.id === id
      );

      if (!foundModel) {
        this.loadError.set(true);
        return;
      }

      this.model.set(foundModel);

      await Promise.all([
        this.loadCalibrationLogs(foundModel.name),
        this.loadPerformance(id),
      ]);

      const logs = this.availableLogs();

      if (logs.length > 0) {
        this.selectedLogProviderId.set(logs[0].providerId);
      }

    } catch {
      this.loadError.set(true);
    } finally {
      this.loading.set(false);
    }
  }

  private async loadCalibrationLogs(modelName: string): Promise<void> {
    try {
      const response =
        await firstValueFrom(
          this.http.post<{ logs: BackendCalibrationLog[] }>(
            '/api/logosdb/get_model_calibration_logs',
            { id: this.modelId() }
          )
        );

      const logs = response.logs ?? [];

      this.modelLogs.set(
        logs.map(log => ({
          providerId: log.provider_id,
          node: log.provider_name,
          modelName,
        }))
      );

      this.rawLogsByProviderId.set(
        new Map(logs.map(log => [log.provider_id, log.log_text ?? '']))
      );

      this.calibrationResults.set(
        logs.map(log =>
          this.parseCalibrationResult(
            log.provider_id,
            log.provider_name,
            log.log_text ?? '',
            log.success,
            log.unsupported_reason,
            log.node_unhealthy_reason,
            log.observed_reason,
            log.stages
          )
        )
      );

    } catch {
      this.modelLogs.set([]);
      this.rawLogsByProviderId.set(new Map());
      this.calibrationResults.set([]);
    }
  }

  async loadPerformance(modelId = this.modelId(), silent = false): Promise<void> {
    if (modelId == null) {
      return;
    }

    if (!silent) {
      this.performanceLoading.set(true);
    }
    this.performanceError.set(false);

    try {
      const response = await this.modelService.getBenchmarks(modelId);
      this.performance.set(response.benchmarks);
      this.benchmarkPairs.set(response.pairs ?? []);
      this.benchmarkRuns.set(response.runs ?? []);
    } catch {
      if (!silent) {
        this.performance.set([]);
        this.benchmarkPairs.set([]);
        this.benchmarkRuns.set([]);
        this.performanceError.set(true);
      }
    } finally {
      if (!silent) {
        this.performanceLoading.set(false);
      }
      this.schedulePerformancePoll();
    }
  }

  async startBenchmark(pair: ModelBenchmarkPair): Promise<void> {
    if (this.providerHasActiveBenchmark(pair.provider_id) || !pair.endpoint_configured) {
      return;
    }
    const confirmed = window.confirm(
      `Start the benchmark on ${pair.provider_name} · ${pair.model_name}?\n\nConfirm that this provider is currently safe for benchmark traffic. The benchmark runs at low priority and stops automatically when production load is detected.`,
    );
    if (!confirmed) return;

    this.benchmarkStartingPairId.set(pair.model_provider_id);
    this.benchmarkStartError.set(null);
    try {
      await this.modelService.startBenchmark(pair.model_provider_id, this.benchmarkSampleSize());
      await this.loadPerformance(this.modelId(), true);
    } catch (error) {
      const response = error instanceof HttpErrorResponse ? error.error : null;
      const nestedError = response?.error;
      const message = response?.detail
        ?? (typeof nestedError === 'string' ? nestedError : nestedError?.message);
      this.benchmarkStartError.set(
        typeof message === 'string' ? message : 'Could not start the benchmark.',
      );
      await this.loadPerformance(this.modelId(), true);
    } finally {
      this.benchmarkStartingPairId.set(null);
    }
  }

  async cancelBenchmark(run: ModelBenchmarkRun): Promise<void> {
    this.benchmarkCancellingJobId.set(run.id);
    this.benchmarkStartError.set(null);
    try {
      await this.modelService.cancelBenchmark(run.id);
      await this.loadPerformance(this.modelId(), true);
    } catch {
      this.benchmarkStartError.set('Could not cancel the benchmark.');
    } finally {
      this.benchmarkCancellingJobId.set(null);
    }
  }

  latestBenchmarkRun(modelProviderId: number): ModelBenchmarkRun | null {
    return this.benchmarkRuns().find(
      run => run.request.model_provider_id === modelProviderId,
    ) ?? null;
  }

  providerHasActiveBenchmark(providerId: number): boolean {
    return this.benchmarkRuns().some(
      run => run.request.provider_id === providerId && this.isBenchmarkActive(run),
    );
  }

  isBenchmarkActive(run: ModelBenchmarkRun): boolean {
    return run.status === 'pending' || run.status === 'running';
  }

  benchmarkStatusLabel(run: ModelBenchmarkRun): string {
    if (run.status === 'pending') return `Queued for ${run.request.provider_name}`;
    if (run.status === 'running') {
      if (run.result.stage === 'preparing_worker') return `Preparing ${run.request.provider_name}`;
      if (run.result.stage === 'warming_up') return `Warming up ${run.request.provider_name}`;
      if (run.result.stage === 'benchmarking') {
        const started = run.result.started_samples ?? 0;
        const total = run.result.total_samples ?? run.request.samples;
        return `Running on ${run.request.provider_name} · request ${started}/${total}`;
      }
      return `Running on ${run.request.provider_name}`;
    }
    if (run.status === 'success') return `Completed ${this.formatBenchmarkTimestamp(run.updated_at)}`;
    return `Failed ${this.formatBenchmarkTimestamp(run.updated_at)}`;
  }

  setBenchmarkSampleSize(value: string): void {
    const parsed = Number(value);
    this.benchmarkSampleSize.set(Number.isFinite(parsed) ? Math.min(100, Math.max(1, Math.round(parsed))) : 5);
  }

  formatSampleCount(count: number): string {
    return `${count} ${count === 1 ? 'sample' : 'samples'}`;
  }

  selectBenchmark(modelProviderId: number, value: string): void {
    const benchmarkId = Number(value);
    if (!Number.isInteger(benchmarkId)) return;
    this.selectedBenchmarkIds.update(current => {
      const next = new Map(current);
      next.set(modelProviderId, benchmarkId);
      return next;
    });
  }

  async deleteBenchmark(benchmark: ModelProviderBenchmark): Promise<void> {
    const confirmed = window.confirm(
      `Delete the benchmark run from ${this.formatBenchmarkTimestamp(benchmark.recorded_at)}? This cannot be undone.`,
    );
    if (!confirmed) return;

    this.benchmarkDeletingId.set(benchmark.id);
    this.benchmarkDeleteError.set(null);
    try {
      await this.modelService.deleteBenchmark(benchmark.id);
      this.selectedBenchmarkIds.update(current => {
        const next = new Map(current);
        next.delete(benchmark.model_provider_id);
        return next;
      });
      await this.loadPerformance(this.modelId(), true);
    } catch {
      this.benchmarkDeleteError.set('Could not delete the selected benchmark run.');
    } finally {
      this.benchmarkDeletingId.set(null);
    }
  }

  private schedulePerformancePoll(): void {
    this.clearPerformancePoll();
    if (this.destroyed) {
      return;
    }
    const hasActiveRun = this.benchmarkRuns().some(run => this.isBenchmarkActive(run));
    if (!hasActiveRun && this.activeTab() !== 'performance') {
      return;
    }
    this.performancePollTimer = setTimeout(() => {
      void this.loadPerformance(this.modelId(), true);
    }, hasActiveRun ? 2500 : 15000);
  }

  private clearPerformancePoll(): void {
    if (this.performancePollTimer !== null) {
      clearTimeout(this.performancePollTimer);
      this.performancePollTimer = null;
    }
  }


  // ==========================================================================
  // Navigation
  // ==========================================================================

  setTab(tab: ModelErrorTab): void {
    this.activeTab.set(tab);
    if (tab === 'performance') {
      void this.loadPerformance(this.modelId(), true);
    } else {
      this.schedulePerformancePoll();
    }
  }

  formatDuration(milliseconds: number | null): string {
    if (milliseconds === null || !Number.isFinite(milliseconds)) return '—';
    if (milliseconds < 1) return '<1 ms';
    if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
    const seconds = milliseconds / 1000;
    return `${seconds.toFixed(seconds >= 10 ? 1 : 2)} s`;
  }

  formatBenchmarkDuration(
    metric: GuideLlmStatusDistributionSummary | undefined,
    percentile: 'p50' | 'p95' | 'p99' | 'p100',
    unit: 'milliseconds' | 'seconds' = 'milliseconds',
  ): string {
    const value = percentile === 'p100'
      ? metric?.successful.max ?? null
      : metric?.successful.percentiles[percentile] ?? null;
    return this.formatDuration(value === null || unit === 'milliseconds' ? value : value * 1000);
  }

  formatBenchmarkRate(
    metric: GuideLlmStatusDistributionSummary | undefined,
    statistic: 'mean' | 'p50' | 'p95',
  ): string {
    const value = statistic === 'mean'
      ? metric?.successful.mean
      : metric?.successful.percentiles[statistic];
    return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(1)} tok/s`;
  }

  formatBenchmarkTimestamp(timestamp: string): string {
    return new Date(timestamp).toLocaleString(undefined, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZoneName: 'short',
    });
  }

  benchmarkProfile(benchmark: ModelProviderBenchmark): string {
    const benchmarkConfig = benchmark.configuration['benchmark'];
    if (this.isRecord(benchmarkConfig)) {
      const profile = benchmarkConfig['profile'];
      if (this.isRecord(profile) && typeof profile['kind'] === 'string') {
        return profile['kind'];
      }
      if (typeof benchmarkConfig['kind'] === 'string') {
        return benchmarkConfig['kind'];
      }
    }

    const scenario = benchmark.configuration['scenario'];
    if (this.isRecord(scenario)) {
      const profile = scenario['profile'];
      if (this.isRecord(profile) && typeof profile['kind'] === 'string') {
        return profile['kind'];
      }
    }

    return 'GuideLLM';
  }

  configurationRows(benchmark: ModelProviderBenchmark) {
    return benchmarkConfigurationRows(benchmark);
  }

  servingCommand(benchmark: ModelProviderBenchmark): string | null {
    return servingCommand(benchmark);
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null;
  }

  toggleError(name: string): void {
    this.expandedErrors.update(current => {
      const next = new Set(current);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  }

  isErrorExpanded(name: string): boolean {
    return this.expandedErrors().has(name);
  }

  onLogSelectorChange(value: string): void {
    const providerId = Number(value);
    if (!Number.isNaN(providerId)) {
      this.selectedLogProviderId.set(providerId);
    }
  }

  async copyLog(): Promise<void> {
    const providerId = this.selectedLogProviderId();
    const text = this.completeLog();
    if (!text || providerId == null) return;

    if (this.logCopiedResetTimer !== null) {
      clearTimeout(this.logCopiedResetTimer);
    }

    let ok = true;
    try {
      if (!navigator.clipboard) {
        throw new Error('Clipboard API unavailable');
      }
      await navigator.clipboard.writeText(text);
    } catch {
      ok = false;
    }

    this.logCopyResult.set({ providerId, ok });
    this.logCopiedResetTimer = setTimeout(() => {
      this.logCopyResult.set(null);
      this.logCopiedResetTimer = null;
    }, 2000);
  }

  openNodeLog(
    node: string,
    errorMessage?: string
  ): void {
    const log = this.availableLogs().find(
      item => item.node === node
    );

    if (!log) {
      return;
    }

    this.highlightedError.set(errorMessage);
    this.highlightedErrorNode.set(log.providerId);

    this.selectedLogProviderId.set(log.providerId);
    this.activeTab.set('complete_logs');

    setTimeout(() => {
      this.scrollToHighlightedError();
    });
  }

  // ==========================================================================
  // Scope
  // ==========================================================================

  getScopePercentageClass(
    scope?: ErrorScope,
    status?: 'success' | 'failure'
  ): string {
    if (!scope) {
      return '';
    }

    const totalNodes = this.availableLogs().length;

    if (totalNodes === 0) {
      return 'scope-badge--danger';
    }

    const nodeCount = scope.nodes?.length ?? 0;

    const successfulNodes =
      status === 'failure'
        ? totalNodes - nodeCount
        : nodeCount;

    const percentage =
      (successfulNodes / totalNodes) * 100;

    if (percentage >= 80) {
      return 'scope-badge--success';
    }

    if (percentage >= 50) {
      return 'scope-badge--warning';
    }

    return 'scope-badge--danger';
  }

  getScopeLabel(
    scope?: ErrorScope,
    status?: 'success' | 'failure'
  ): string {
    if (!scope) {
      return '';
    }

    if (scope.type === 'global') {
      return '100%';
    }

    const totalNodes = this.availableLogs().length;

    if (totalNodes === 0) {
      return '0%';
    }

    const nodeCount = scope.nodes?.length ?? 0;

    const successfulNodes =
      status === 'failure'
        ? totalNodes - nodeCount
        : nodeCount;

    return `${Math.round(
      (successfulNodes / totalNodes) * 100
    )}%`;
  }

  getScopeDetails(scope?: ErrorScope): string {
    if (!scope) {
      return '';
    }

    if (scope.type === 'global') {
      return 'Global';
    }

    return scope.nodes?.join(', ') ?? '';
  }


  // ==========================================================================
  // Log Highlighting
  // ==========================================================================

  private scrollToHighlightedError(): void {
    const index = this.highlightedLogLineIndex();

    if (index < 0) {
      return;
    }

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        this.logViewport()?.scrollToIndex(index, 'smooth');
      });
    });
  }


  // ==========================================================================
  // Log Parsing
  // ==========================================================================

  // Precedence mirrors the worker's own override rule
  // (_override_error_if_unsupported, calibration.py:1650-1667): a
  // degraded node invalidates every measurement in the run, so
  // node_unhealthy wins over unsupported when both are somehow set.
  private resolveAuthoritativeReason(
    unsupportedReason: string | null,
    nodeUnhealthyReason: string | null,
    observedReason: string | null
  ): AuthoritativeReason | undefined {
    if (nodeUnhealthyReason) {
      return {
        kind: 'node_unhealthy',
        code: nodeUnhealthyReason,
        ...lookupReason('node_unhealthy', nodeUnhealthyReason),
      };
    }
    if (unsupportedReason) {
      return {
        kind: 'unsupported',
        code: unsupportedReason,
        ...lookupReason('unsupported', unsupportedReason),
      };
    }
    if (observedReason) {
      return {
        kind: 'observed',
        code: observedReason,
        ...lookupReason('observed', observedReason),
      };
    }
    return undefined;
  }

  // Backend-supplied stage-by-stage checklist for the deciding failed
  // probe (see _classify_calibration_stages, calibration.py) — when
  // present, the worker is authoritative and no log_text parsing is
  // needed at all. Only ever set for failed calibrations (see the
  // scope note in model-error-report's implementation plan).
  private buildProbeResultFromBackendStages(
    backendStages: readonly BackendStageResult[]
  ): CalibrationProbeResult {
    const stages: CalibrationStageResult[] = backendStages.map(stage => {
      if (stage.status !== 'failure') {
        return { name: stage.name, status: stage.status };
      }

      const reasonKind = stage.reason_kind ?? undefined;
      const reasonCode = stage.reason_code ?? undefined;
      // The backend places the failure on the resolved stage's ROW
      // (stage.name is that stage's label) but doesn't send display
      // text — look up the domain id for that label so a
      // positionally-resolved reason (e.g. cuda-oom) picks its
      // phase-specific wording instead of the generic one.
      const domainId = CALIBRATION_DOMAINS.find(
        domain => domain.label === stage.name
      )?.id;
      const resolved =
        reasonKind && reasonCode
          ? lookupReason(reasonKind, reasonCode, domainId)
          : undefined;

      return {
        name: stage.name,
        status: 'failure',
        errorMessage: resolved?.label ?? stage.generic_error_message ?? undefined,
        errorDetail: resolved?.description ?? stage.generic_error_detail ?? undefined,
        reasonKind,
        reasonCode,
        // The backend already computed the raw-log anchor (pattern
        // needle, or the generic grep's own raw summary line) — use it
        // directly rather than re-deriving via the frontend's own
        // reason tables.
        logAnchor: stage.log_anchor ?? undefined,
      };
    });

    const failedStage = stages.find(stage => stage.status === 'failure');

    return {
      probe: 1,
      status: 'failure',
      stages,
      errorMessage: failedStage?.errorMessage,
      errorDetail: failedStage?.errorDetail,
      reasonKind: failedStage?.reasonKind,
      reasonCode: failedStage?.reasonCode,
      logAnchor: failedStage?.logAnchor,
    };
  }

  private parseCalibrationResult(
    providerId: number,
    node: string,
    log: string,
    success: boolean,
    unsupportedReason: string | null = null,
    nodeUnhealthyReason: string | null = null,
    observedReason: string | null = null,
    backendStages: readonly BackendStageResult[] | null = null
  ): NodeCalibrationResult {
    if (backendStages && backendStages.length > 0) {
      const probe = this.buildProbeResultFromBackendStages(backendStages);
      return {
        providerId,
        node,
        attempts: 1,
        status: probe.status,
        probes: [probe],
      };
    }

    const authoritativeReason = this.resolveAuthoritativeReason(
      unsupportedReason,
      nodeUnhealthyReason,
      observedReason
    );

    const probeBlocks = log
      .split(/(?=\s*Calibration probe\s*[—-])/)
      .filter(block =>
        /Calibration probe\s*[—-]/.test(block)
      );

    if (probeBlocks.length === 0) {
      // Nothing matches the expected "Calibration probe — ..." format
      // (log format changed, or log_text is empty/unexpected) — fall
      // back to the calibration's actual recorded outcome.
      if (success) {
        return { providerId, node, attempts: 0, status: 'success', probes: [] };
      }
      const error = this.getCalibrationError(log);
      const errorMessage =
        authoritativeReason?.label ??
        error?.summary ??
        'Calibration failed — log format not recognized, see Complete Logs for details.';
      const errorDetail = authoritativeReason?.description ?? error?.detail;
      const logAnchor = authoritativeReason?.needle ?? error?.summary;
      return {
        providerId,
        node,
        attempts: 0,
        status: 'failure',
        probes: [
          {
            probe: 1,
            status: 'failure',
            errorMessage,
            errorDetail,
            reasonKind: authoritativeReason?.kind,
            reasonCode: authoritativeReason?.code,
            logAnchor,
            stages: [
              {
                name: CALIBRATION_DOMAINS[0].label,
                status: 'failure',
                errorMessage,
                errorDetail,
                reasonKind: authoritativeReason?.kind,
                reasonCode: authoritativeReason?.code,
                logAnchor,
              },
            ],
          },
        ],
      };
    }

    const probes = probeBlocks.map(
      (block, index) =>
        this.parseCalibrationProbe(
          index + 1,
          block,
          success,
          authoritativeReason
        )
    );

    const successfulProbe = probes.find(
      probe => probe.status === 'success'
    );

    if (successfulProbe) {
      return {
        providerId,
        node,
        attempts: probes.length,
        status: 'success',
        probes,
      };
    }

    const failedProbe = probes.find(
      probe => probe.status === 'failure'
    );

    return {
      providerId,
      node,
      attempts: probes.length,
      status: failedProbe
        ? 'failure'
        : 'unknown',
      probes,
    };
  }

  private parseCalibrationProbe(
    probeNumber: number,
    block: string,
    success: boolean,
    authoritativeReason?: AuthoritativeReason
  ): CalibrationProbeResult {
    // A domain with no completion pattern of its own (Node Preflight,
    // Multi-GPU Coordination) is inferred complete once a LATER domain's
    // pattern matches — ports calibration.py's _classify_calibration_stages
    // algorithm 1:1.
    const completed = CALIBRATION_DOMAINS.map(domain =>
      domain.completionPatterns.some(pattern => pattern.test(block))
    );
    for (let index = 0; index < CALIBRATION_DOMAINS.length; index++) {
      if (CALIBRATION_DOMAINS[index].completionPatterns.length === 0) {
        completed[index] = completed.slice(index + 1).some(Boolean);
      }
    }

    const stages: CalibrationStageResult[] = CALIBRATION_DOMAINS.map(
      (domain, index) => ({
        name: domain.label,
        status: completed[index] ? 'success' : 'unknown',
      })
    );

    const serverStartDomain = CALIBRATION_DOMAINS[CALIBRATION_DOMAINS.length - 1];
    const deploymentSuccessful =
      success &&
      serverStartDomain.completionPatterns.some(pattern => pattern.test(block));

    if (deploymentSuccessful) {
      return {
        probe: probeNumber,
        status: 'success',
        stages,
      };
    }

    // A known reason's domain pinpoints the failing row more precisely
    // than "first domain whose completion signal wasn't seen yet" —
    // prefer it when declared, else fall back to the positional
    // heuristic (correct for errors like CUDA OOM that can occur at
    // more than one point — see CALIBRATION_DOMAINS' module note).
    const mappedIndex = authoritativeReason?.domain
      ? CALIBRATION_DOMAINS.findIndex(
          domain => domain.id === authoritativeReason.domain
        )
      : -1;
    const firstIncompleteIndex = completed.findIndex(done => !done);
    const effectiveIndex =
      mappedIndex !== -1 ? mappedIndex : firstIncompleteIndex;

    if (effectiveIndex !== -1) {
      const error = authoritativeReason
        ? undefined
        : this.getCalibrationError(block);

      // Re-resolve display text now that the ACTUAL landing stage is
      // known — for a positionally-resolved reason (e.g. cuda-oom) this
      // picks the phase-specific wording (see domainOverrides) instead
      // of the generic one picked at node-level resolution time.
      const resolved = authoritativeReason
        ? lookupReason(
            authoritativeReason.kind,
            authoritativeReason.code,
            CALIBRATION_DOMAINS[effectiveIndex]?.id
          )
        : undefined;

      const errorMessage = resolved?.label ?? error?.summary;
      const errorDetail = resolved?.description ?? error?.detail;
      // Raw-log substring for the scroll-to-line search — the reason's
      // needle if classified, else the generic grep's own (already raw)
      // summary line. NEVER the polished errorMessage above, which
      // won't itself appear verbatim in the log for a classified reason.
      const logAnchor = authoritativeReason?.needle ?? error?.summary;

      stages[effectiveIndex] = {
        ...stages[effectiveIndex],
        status: 'failure',
        errorMessage,
        errorDetail,
        reasonKind: authoritativeReason?.kind,
        reasonCode: authoritativeReason?.code,
        logAnchor,
      };

      return {
        probe: probeNumber,
        status: 'failure',
        stages,
        errorMessage,
        errorDetail,
        reasonKind: authoritativeReason?.kind,
        reasonCode: authoritativeReason?.code,
        logAnchor,
      };
    }

    return {
      probe: probeNumber,
      status: 'unknown',
      stages,
    };
  }

  private getCalibrationError(
    block: string
  ): CalibrationError | undefined {
    const lines = block
      .split('\n')
      .filter(line => line.trim().length > 0);

    // The trigger keyword (e.g. "Traceback") often lands on a different
    // line than the marker that identifies a known-benign block (e.g.
    // "Module numba was found but failed to import" one line above it)
    // — check a small preceding window, not just the matched line
    // itself. Mirrors _is_ignored in calibration.py.
    const isIgnored = (index: number): boolean => {
      const window = lines.slice(
        Math.max(0, index - GENERIC_CALIBRATION_ERROR_IGNORE_WINDOW),
        index + 1
      );
      return window.some(windowLine =>
        GENERIC_CALIBRATION_ERROR_IGNORE_NEEDLES.some(needle =>
          windowLine.includes(needle)
        )
      );
    };

    const errorIndex = lines.findIndex(
      (line, index) =>
        /\b(?:ERROR|CRITICAL|FATAL|Exception|Traceback|ValueError|RuntimeError|TypeError|KeyError|ImportError|AssertionError)\b/
          .test(line) && !isIgnored(index)
    );

    const index =
      errorIndex !== -1
        ? errorIndex
        : lines.findIndex(
            (line, i) => /\berror\s*:/i.test(line) && !isIgnored(i)
          );

    if (index === -1) {
      return undefined;
    }

    return {
      summary: lines[index],
      detail: lines.slice(index).join('\n'),
    };
  }


  // ==========================================================================
  // Checklist
  // ==========================================================================

  private getCalibrationChecklistItems(): ChecklistItem[] {
    const results = this.calibrationResults();

    if (!results.length) {
      return [];
    }

    const items: ChecklistItem[] = [];

    for (const stage of CALIBRATION_DOMAINS) {
      const successfulNodes: string[] = [];
      const failedNodes: string[] = [];
      const failures = new Map<
        string,
        {
          nodes: string[];
          detail?: string;
          reasonKind?: AuthoritativeReasonKind;
          reasonCode?: string;
          logAnchor?: string;
        }
      >();

      for (const result of results) {
        const stageResults =
          result.probes
            .map(probe =>
              probe.stages.find(
                item =>
                  item.name === stage.label
              )
            )
            .filter(
              (
                item
              ): item is CalibrationStageResult =>
                !!item
            );

        const successful =
          stageResults.some(
            stageResult =>
              stageResult.status === 'success'
          );

        if (successful) {
          successfulNodes.push(result.node);
          continue;
        }

        const failedStageResults =
          stageResults.filter(
            stageResult =>
              stageResult.status === 'failure'
          );

        for (const stageResult of failedStageResults) {
          const error =
            stageResult.errorMessage ??
            'Unknown calibration error';

          const entry =
            failures.get(error) ?? {
              nodes: [],
              detail: stageResult.errorDetail,
              reasonKind: stageResult.reasonKind,
              reasonCode: stageResult.reasonCode,
              logAnchor: stageResult.logAnchor,
            };

          entry.nodes.push(result.node);

          failures.set(error, entry);
          failedNodes.push(result.node);
        }
      }

      const uniqueSuccessfulNodes = [
        ...new Set(successfulNodes),
      ];

      const uniqueFailedNodes = [
        ...new Set(failedNodes),
      ];

      if (uniqueFailedNodes.length > 0) {
        const [firstError, firstEntry] =
          [...failures.entries()][0] ?? [];

        items.push({
          name: stage.label,
          status: 'failure',
          scope: {
            type: 'node',
            nodes: uniqueFailedNodes,
          },
          errorMessage: firstError ?? 'Unknown calibration error',
          errorDetail: firstEntry?.detail,
          reasonKind: firstEntry?.reasonKind,
          reasonCode: firstEntry?.reasonCode,
          logAnchor: firstEntry?.logAnchor,
        });

        continue;
      }

      if (uniqueSuccessfulNodes.length > 0) {
        items.push({
          name: stage.label,
          status: 'success',
          scope: {
            type: 'node',
            nodes: uniqueSuccessfulNodes,
          },
        });
      }
    }

    return items;
  }

}
