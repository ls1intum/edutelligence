import {
  ChangeDetectionStrategy,
  Component,
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
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

import { ModelManagementService } from '../../core/services/model-management.service';
import { Model } from '../../shared/models/model.model';

import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';


// ==========================================================================
// Types
// ==========================================================================

type ModelErrorTab =
  | 'error_report'
  | 'complete_logs';

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
}

interface ModelProcessDefinition {
  readonly id: number;
  readonly process: string;
  readonly checklist: string;
}

interface ModelProcess {
  readonly id: number;
  readonly process: string;
  readonly status: 'success' | 'failure';
  readonly checklist: string;
  readonly items: readonly ChecklistItem[];
}

interface CalibrationStage {
  readonly name: string;
  readonly successPatterns: readonly RegExp[];
}

interface CalibrationStageResult {
  readonly name: string;
  readonly status: CalibrationStatus;
  readonly errorMessage?: string;
  readonly errorDetail?: string;
}

interface CalibrationProbeResult {
  readonly probe: number;
  readonly status: CalibrationStatus;
  readonly stages: readonly CalibrationStageResult[];
  readonly errorMessage?: string;
  readonly errorDetail?: string;
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

interface BackendCalibrationLog {
  readonly provider_id: number;
  readonly provider_name: string;
  readonly success: boolean;
  readonly probe_command: string | null;
  readonly error: string | null;
  readonly log_text: string | null;
  readonly recorded_at: string | null;
  readonly updated_at: string;
}


// ==========================================================================
// Process Definitions
// ==========================================================================

const PROCESS_DEFINITIONS: readonly ModelProcessDefinition[] = [
  {
    id: 1,
    process: 'Download',
    checklist: 'Download',
  },
  {
    id: 2,
    process: 'Initialization',
    checklist: 'Initialization',
  },
];


// ==========================================================================
// Calibration Stages
// ==========================================================================

const CALIBRATION_STAGES: readonly CalibrationStage[] = [
  {
    name: 'Model Identification',
    successPatterns: [
      /non-default args:/,
    ],
  },
  {
    name: 'Model Download',
    successPatterns: [
      /non-default args:/,
    ],
  },
  {
    name: 'Initialized vLLM engine',
    successPatterns: [
      /Initializing a V1 LLM engine/,
    ],
  },
  {
    name: 'Downloaded Weights',
    successPatterns: [
      /Time spent downloading weights/,
    ],
  },
  {
    name: 'Loaded Safetensor Checkpoints',
    successPatterns: [
      /Loading safetensors checkpoint shards:\s*100%\s*Completed/,
    ],
  },
  {
    name: 'Loaded Weights',
    successPatterns: [
      /Loading weights took/,
    ],
  },
  {
    name: 'Loaded Model',
    successPatterns: [
      /Model loading took/,
    ],
  },
  {
    name: 'Completed Warmup Run',
    successPatterns: [
      /Initial profiling\/warmup run took/,
    ],
  },
  {
    name: 'Reserved KV-Cache Memory',
    successPatterns: [
      /reserved .* memory for KV Cache/,
    ],
  },
  {
    name: 'Engine Core Started',
    successPatterns: [
      /GPU KV cache size:/,
    ],
  },
  {
    name: 'Start vLLM Server',
    successPatterns: [
      /Starting vLLM server on/,
    ],
  },
  {
    name: 'Deployment Success',
    successPatterns: [
      /Application startup complete\./,
      /"GET \/health HTTP\/1\.1"\s+200\s+OK/,
    ],
  },
];


@Component({
  selector: 'app-model-error-report',
  standalone: true,

  imports: [
    RouterLink,
    NgClass,
    ScrollingModule,
    ErrorMessageComponent,
    DataTableComponent,
  ],

  templateUrl: './model-error-report.html',
  styleUrl: './model-error-report.scss',

  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModelErrorReport implements OnInit {

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

  readonly activeTab = signal<ModelErrorTab>('complete_logs');

  readonly expandedProcess = signal<number[]>([]);

  private readonly expandedErrors = signal<ReadonlySet<string>>(new Set());

  readonly selectedLogProviderId = signal<number | null>(null);

  readonly logCopied = signal(false);

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

  readonly processesLoading = signal(false);

  // ==========================================================================
  // Tabs
  // ==========================================================================

  readonly tabs: readonly ModelErrorTab[] = [
    'complete_logs',
  ];

  readonly tabLabel: Record<ModelErrorTab, string> = {
    error_report: 'Error Report',
    complete_logs: 'Complete Logs',
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
  // Process Data
  // ==========================================================================

  readonly processes =
    computed<readonly ModelProcess[]>(() => {
      if (!this.model()) {
        return [];
      }

      return PROCESS_DEFINITIONS.map(definition => {
        const items =
          this.getCalibrationChecklistItems(
            definition.process
          );

        const hasFailure = items.some(
          item => item.status === 'failure'
        );

        return {
          id: definition.id,
          process: definition.process,
          checklist: definition.checklist,
          status: hasFailure
            ? 'failure'
            : 'success',
          items,
        };
      });
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

      await this.loadCalibrationLogs(foundModel.name);

      const logs = this.availableLogs();

      if (logs.length > 0) {
        this.selectedLogProviderId.set(logs[0].providerId);
      }

      this.expandFailedProcesses();

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
          this.parseCalibrationResult(log.provider_id, log.provider_name, log.log_text ?? '', log.success)
        )
      );

    } catch {
      this.modelLogs.set([]);
      this.rawLogsByProviderId.set(new Map());
      this.calibrationResults.set([]);
    }
  }


  // ==========================================================================
  // Navigation
  // ==========================================================================

  setTab(tab: ModelErrorTab): void {
    this.activeTab.set(tab);
  }

  toggleProcess(id: number): void {
    this.expandedProcess.update(current => {
      if (current.includes(id)) {
        return current.filter(
          processId => processId !== id
        );
      }

      return [...current, id];
    });
  }

  isExpanded(id: number): boolean {
    return this.expandedProcess().includes(id);
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
    const text = this.completeLog();
    if (!text) return;
    await navigator.clipboard.writeText(text);
    this.logCopied.set(true);
    setTimeout(() => this.logCopied.set(false), 2000);
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

  private expandFailedProcesses(): void {
    this.expandedProcess.set(
      this.processes()
        .filter(
          process => process.status === 'failure'
        )
        .map(process => process.id)
    );
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

  private parseCalibrationResult(
    providerId: number,
    node: string,
    log: string,
    success: boolean
  ): NodeCalibrationResult {
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
        error?.summary ??
        'Calibration failed — log format not recognized, see Complete Logs for details.';
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
            errorDetail: error?.detail,
            stages: [
              {
                name: CALIBRATION_STAGES[0].name,
                status: 'failure',
                errorMessage,
                errorDetail: error?.detail,
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
          success
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
    success: boolean
  ): CalibrationProbeResult {
    const stages: CalibrationStageResult[] = [];

    let firstFailedStageIndex = -1;

    for (
      let index = 0;
      index < CALIBRATION_STAGES.length;
      index++
    ) {
      const stage = CALIBRATION_STAGES[index];

      const patternMatched =
        stage.successPatterns.some(
          pattern => pattern.test(block)
        );

      const successful =
        stage.name === 'Deployment Success'
          ? success && patternMatched
          : patternMatched;

      if (successful) {
        stages.push({
          name: stage.name,
          status: 'success',
        });

        continue;
      }

      if (firstFailedStageIndex === -1) {
        firstFailedStageIndex = index;
      }

      stages.push({
        name: stage.name,
        status: 'unknown',
      });
    }

    const deploymentSuccessful =
      success &&
      stages.some(
        stage =>
          stage.name === 'Deployment Success' &&
          stage.status === 'success'
      );

    if (deploymentSuccessful) {
      return {
        probe: probeNumber,
        status: 'success',
        stages,
      };
    }

    if (firstFailedStageIndex !== -1) {
      const error = this.getCalibrationError(block);

      const failedStage =
        stages[firstFailedStageIndex];

      stages[firstFailedStageIndex] = {
        ...failedStage,
        status: 'failure',
        errorMessage: error?.summary,
        errorDetail: error?.detail,
      };

      return {
        probe: probeNumber,
        status: 'failure',
        stages,
        errorMessage: error?.summary,
        errorDetail: error?.detail,
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

    const errorIndex = lines.findIndex(line =>
      /\b(?:ERROR|CRITICAL|FATAL|Exception|Traceback|ValueError|RuntimeError|TypeError|KeyError|ImportError|AssertionError)\b/
        .test(line)
    );

    const index =
      errorIndex !== -1
        ? errorIndex
        : lines.findIndex(line => /\berror\s*:/i.test(line));

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

  private getCalibrationChecklistItems(
    processName: string
  ): ChecklistItem[] {
    const results = this.calibrationResults();

    if (!results.length) {
      return [];
    }

    const stages =
      this.getStagesForProcess(processName);

    const items: ChecklistItem[] = [];

    for (const stage of stages) {
      const successfulNodes: string[] = [];
      const failedNodes: string[] = [];
      const failures = new Map<
        string,
        { nodes: string[]; detail?: string }
      >();

      for (const result of results) {
        const stageResults =
          result.probes
            .map(probe =>
              probe.stages.find(
                item =>
                  item.name === stage.name
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
            failures.get(error) ?? { nodes: [], detail: stageResult.errorDetail };

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
          name: stage.name,
          status: 'failure',
          scope: {
            type: 'node',
            nodes: uniqueFailedNodes,
          },
          errorMessage: firstError ?? 'Unknown calibration error',
          errorDetail: firstEntry?.detail,
        });

        continue;
      }

      if (uniqueSuccessfulNodes.length > 0) {
        items.push({
          name: stage.name,
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

  private getStagesForProcess(
    processName: string
  ): readonly CalibrationStage[] {
    if (processName === 'Download') {
      return CALIBRATION_STAGES.filter(
        stage =>
          stage.name === 'Model Identification' ||
          stage.name === 'Model Download'
      );
    }

    return CALIBRATION_STAGES.filter(
      stage =>
        stage.name !== 'Model Identification' &&
        stage.name !== 'Model Download'
    );
  }
}