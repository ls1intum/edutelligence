import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
  effect,
  ElementRef,
  QueryList,
  ViewChildren,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { ModelManagementService } from '../../core/services/model-management.service';
import { Model } from '../../shared/models/model.model';

import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';


type ModelErrorTab =
  | 'error_report'
  | 'complete_logs';


interface ErrorScope {
  readonly type: 'global' | 'node';
  readonly nodes?: readonly string[];
}


interface ChecklistItem {
  readonly name: string;
  readonly status: 'success' | 'failure';
  readonly errorMessage?: string;
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


type CalibrationStatus =
  | 'success'
  | 'failure'
  | 'unknown';


interface CalibrationStage {
  readonly name: string;
  readonly successPatterns: readonly RegExp[];
}


interface CalibrationStageResult {
  readonly name: string;
  readonly status: CalibrationStatus;
  readonly errorMessage?: string;
}


interface CalibrationProbeResult {
  readonly probe: number;
  readonly status: CalibrationStatus;
  readonly stages: readonly CalibrationStageResult[];
  readonly errorMessage?: string;
}


interface NodeCalibrationResult {
  readonly node: string;
  readonly status: CalibrationStatus;
  readonly attempts: number;
  readonly probes: readonly CalibrationProbeResult[];
}


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


interface ModelLog {
  readonly node: string;
  readonly file: string;
  readonly modelName: string;
}


@Component({
  selector: 'app-model-error-report',
  standalone: true,

  imports: [
    RouterLink,
    ErrorMessageComponent,
    DataTableComponent,
  ],

  templateUrl: './model-error-report.html',
  styleUrl: './model-error-report.scss',

  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModelErrorReport implements OnInit {

  private readonly route = inject(ActivatedRoute);

  private readonly modelService =
    inject(ModelManagementService);

  private readonly http =
    inject(HttpClient);

  private readonly modelLogs =
    signal<readonly ModelLog[]>([]);


  readonly tabs: readonly ModelErrorTab[] = [
    'error_report',
    'complete_logs',
  ];


  readonly visibleTabs =
    computed<readonly ModelErrorTab[]>(() => {
      if (this.hasCompleteLogs()) {
        return this.tabs;
      }

      return ['error_report'];
    });


  readonly tabLabel:
    Record<ModelErrorTab, string> = {
      error_report: 'Error Report',
      complete_logs: 'Complete Logs',
    };


  readonly model =
    signal<Model | null>(null);


  readonly modelId =
    signal<number | null>(null);


  readonly loading =
    signal(true);


  readonly loadError =
    signal(false);


  readonly completeLog =
    signal('');


  readonly logLines =
    computed(() =>
      this.completeLog().split('\n')
    );


  private readonly calibrationResults =
    signal<readonly NodeCalibrationResult[]>([]);


  readonly calibrationResult =
    computed<NodeCalibrationResult | null>(() => {
      const selectedLog =
        this.selectedLog();

      const result = selectedLog
        ? this.calibrationResults()
            .find(item =>
              item.node === selectedLog.node
            ) ?? null
        : null;

      return result;
    });


  readonly hasCompleteLogs = computed(() => {
    const currentModel = this.model();

    if (!currentModel) {
      return false;
    }

    return this.modelLogs().some(
      log => log.modelName === currentModel.name
    );
  });


  readonly selectedLogNode =
    signal<string | null>(null);


  readonly availableLogs = computed(() => {
    const currentModel = this.model();

    if (!currentModel) {
      return [];
    }

    return this.modelLogs()
      .filter(log =>
        log.modelName === currentModel.name
      );
  });


  readonly selectedLog =
    computed(() => {
      const logs =
        this.availableLogs();

      if (!logs.length) {
        return null;
      }

      const selectedNode =
        this.selectedLogNode();

      return (
        logs.find(log =>
          log.node === selectedNode
        )
        ?? logs[0]
      );
    });


  constructor() {
    effect(() => {
      const log =
        this.selectedLog();

      if (!log) {
        return;
      }

      void this.loadLog(log.file);
    });
  }


  readonly activeTab =
    signal<ModelErrorTab>(
      'error_report'
    );


  readonly processesLoading =
    signal(false);


  readonly expandedProcess =
    signal<number[]>([]);


  readonly processes =
  computed<readonly ModelProcess[]>(() => {

    if (!this.model()) {
      return [];
    }

    return PROCESS_DEFINITIONS.map(
      definition => {

        const items =
          this.getCalibrationChecklistItems(
            definition.process
          );

        const hasFailure =
          items.some(item =>
            item.status === 'failure'
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
      }
    );
  });

  @ViewChildren(
    'logLine',
    { read: ElementRef }
  )
  private readonly logLineElements!: QueryList<ElementRef<HTMLDivElement>>;

  readonly highlightedError =
    signal<string | undefined>(undefined);

  async ngOnInit(): Promise<void> {
    const id =
      Number(
        this.route.snapshot.paramMap.get('id')
      );

    this.modelId.set(id);

    await this.fetchModel(id);
  }


  async fetchModel(
    id: number
  ): Promise<void> {
    this.loading.set(true);
    this.loadError.set(false);

    try {
      const models =
        await this.modelService.getModels();

      const foundModel =
        models.find(
          model => model.id === id
        );

      if (!foundModel) {
        this.loadError.set(true);
        return;
      }

      this.model.set(foundModel);

      await this.loadLogIndex();

      const logs =
        this.availableLogs();

      await this.loadAllCalibrationLogs(logs);

      if (logs.length) {
        this.selectedLogNode.set(
          logs[0].node
        );
      }

      this.expandFailedProcesses();

    } catch {
      this.loadError.set(true);

    } finally {
      this.loading.set(false);
    }
  }


  setTab(
    tab: ModelErrorTab
  ): void {
    this.activeTab.set(tab);
  }


  toggleProcess(
    id: number
  ): void {
    this.expandedProcess.update(
      current => {
        if (current.includes(id)) {
          return current.filter(
            processId =>
              processId !== id
          );
        }

        return [
          ...current,
          id,
        ];
      }
    );
  }


  isExpanded(
    id: number
  ): boolean {
    return this.expandedProcess()
      .includes(id);
  }


  private expandFailedProcesses(): void {
    this.expandedProcess.set(
      this.processes()
        .filter(process =>
          process.status === 'failure'
        )
        .map(process =>
          process.id
        )
    );
  }

  private async loadAllCalibrationLogs(
    logs: readonly ModelLog[]
  ): Promise<void> {
    const results = await Promise.all(
      logs.map(async log => {
        try {
          const content =
            await firstValueFrom(
              this.http.get(
                `/logs/${log.file}`,
                {
                  responseType: 'text',
                }
              )
            );

          return this.parseCalibrationResult(
            log.node,
            content
          );
        } catch {
          return null;
        }
      })
    );

    this.calibrationResults.set(
      results.filter(
        (
          result
        ): result is NodeCalibrationResult =>
          result !== null
      )
    );
  }


  getScopeLabel(
    scope?: ErrorScope
  ): string {
    if (!scope) {
      return '';
    }

    if (scope.type === 'global') {
      return 'Global';
    }

    const count = scope.nodes?.length ?? 0;

    return `Nodes: ${count}`;
  }


  getScopeDetails(
    scope?: ErrorScope
  ): string {
    if (!scope) {
      return '';
    }

    if (scope.type === 'global') {
      return 'Global';
    }

    return scope.nodes?.join(', ') ?? '';
  }

  openNodeLog(
    node: string,
    errorMessage?: string
  ): void {
    const log =
      this.availableLogs().find(
        item => item.node === node
      );

    if (!log) {
      return;
    }

    this.highlightedError.set(
      errorMessage?.trim()
    );

    this.selectedLogNode.set(node);
    this.activeTab.set('complete_logs');
  }


  private parseLogFilename(
    file: string
  ): ModelLog | null {
    const match =
      file.match(
        /^(.+)-node(\d+)\.log$/
      );

    if (!match) {
      return null;
    }

    const [, modelName, nodeNumber] =
      match;

    return {
      file,
      modelName,
      node: `Node ${nodeNumber}`,
    };
  }

  private async loadLogIndex(): Promise<void> {
    try {
      const files =
        await firstValueFrom(
          this.http.get<string[]>(
            '/logs/index.json'
          )
        );

      const logs =
        files
          .map(file =>
            this.parseLogFilename(file)
          )
          .filter(
            (
              log
            ): log is ModelLog =>
              log !== null
          );

      this.modelLogs.set(logs);

    } catch {
      this.modelLogs.set([]);
    }
  }


  private async loadLog(
    file: string
  ): Promise<void> {
    try {
      const log =
        await firstValueFrom(
          this.http.get(
            `/logs/${file}`,
            {
              responseType: 'text',
            }
          )
        );

      this.completeLog.set(log);

      if (this.highlightedError()) {
        requestAnimationFrame(() => {
          this.scrollToHighlightedError();
        });
      }

    } catch {
      this.completeLog.set(
        'Unable to load log file.'
      );
    }
  }

  private scrollToHighlightedError(): void {
    const error =
      this.highlightedError();

    if (!error) {
      return;
    }

    const elements =
      this.logLineElements.toArray();

    const lines =
      this.logLines();

    const index =
      lines.findIndex(line =>
        this.isHighlightedLogLine(line)
      );

    if (index === -1) {
      return;
    }

    const element =
      elements[index]?.nativeElement;

    if (!element) {
      return;
    }

    element.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    });
  }


  private isSuccessfulCalibrationProbe(
    block: string
  ): boolean {
    return (
      block.includes(
        'Waiting for application startup.'
      ) &&
      block.includes(
        'Application startup complete.'
      ) &&
      /"GET \/health HTTP\/1\.1"\s+200 OK/.test(
        block
      )
    );
  }

  private parseCalibrationResult(
    node: string,
    log: string
  ): NodeCalibrationResult {

    const probeBlocks =
      log
        .split(
          /(?=\s*Calibration probe\s*[—-])/
        )
        .filter(block =>
          /Calibration probe\s*[—-]/
            .test(block)
        );

    const probes: CalibrationProbeResult[] =
      probeBlocks.map(
        (block, index) =>
          this.parseCalibrationProbe(
            index + 1,
            block
          )
      );

    const attempts =
      probes.length;

    const successfulProbe =
      probes.find(probe =>
        probe.status === 'success'
      );

    if (successfulProbe) {
      return {
        node,
        attempts,
        status: 'success',
        probes,
      };
    }

    const failedProbe =
      probes.find(probe =>
        probe.status === 'failure'
      );

    return {
      node,
      attempts,
      status:
        failedProbe
          ? 'failure'
          : attempts > 0
            ? 'unknown'
            : 'unknown',
      probes,
    };
  }

  private parseCalibrationProbe(
    probeNumber: number,
    block: string
  ): CalibrationProbeResult {

    const stages: CalibrationStageResult[] = [];

    let firstFailedStageIndex = -1;

    for (
      let index = 0;
      index < CALIBRATION_STAGES.length;
      index++
    ) {
      const stage =
        CALIBRATION_STAGES[index];

      const successful =
        stage.successPatterns.some(
          pattern =>
            pattern.test(block)
        );

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
      stages.some(stage =>
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
      const errorMessage =
        this.getCalibrationError(block);

      const failedStage =
        stages[firstFailedStageIndex];

      stages[firstFailedStageIndex] = {
        ...failedStage,
        status: 'failure',
        errorMessage,
      };

      return {
        probe: probeNumber,
        status: 'failure',
        stages,
        errorMessage,
      };
    }

    return {
      probe: probeNumber,
      status: 'unknown',
      stages,
    };
  }

  isHighlightedLogLine(
    line: string
  ): boolean {
    const error =
      this.highlightedError();

    if (!error) {
      return false;
    }

    return (
      line.includes(error) ||
      line.trim().includes(error.trim())
    );
  }


  private getCalibrationError(
    block: string
  ): string | undefined {
    const lines =
      block
        .split('\n')
        .filter(line =>
          line.trim().length > 0
        );

    const errorLine =
      lines.find(line =>
        /\b(?:ERROR|Exception|Traceback|ValueError|RuntimeError|TypeError|KeyError|ImportError|AssertionError)\b/
          .test(line)
      );

    if (errorLine) {
      return errorLine;
    }

    return lines.find(line =>
      /\berror\s*:/i.test(line)
    );
  }


  private getCalibrationChecklistItems(
    processName: string
  ): ChecklistItem[] {

    const results =
      this.calibrationResults();

    if (!results.length) {
      return [];
    }

    const items: ChecklistItem[] = [];

    const stages =
      CALIBRATION_STAGES.filter(stage => {
        if (processName === 'Download') {
          return (
            stage.name ===
              'Model Identification' ||
            stage.name ===
              'Model Download'
          );
        }

        return (
          stage.name !==
            'Model Identification' &&
          stage.name !==
            'Model Download'
        );
      });

    for (const stage of stages) {
      const successfulNodes: string[] = [];

      const failures =
        new Map<
          string,
          string[]
        >();

      for (const result of results) {

        const stageResults =
          result.probes
            .map(probe =>
              probe.stages.find(
                item =>
                  item.name ===
                  stage.name
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
              stageResult.status ===
              'success'
          );

        if (successful) {
          successfulNodes.push(
            result.node
          );
          continue;
        }

        const failedStageResults =
          stageResults.filter(
            stageResult =>
              stageResult.status ===
              'failure'
          );

        for (
          const stageResult of
            failedStageResults
        ) {
          const error =
            stageResult.errorMessage ??
            'Unknown calibration error';

          const nodes =
            failures.get(error) ?? [];

          nodes.push(result.node);

          failures.set(
            error,
            nodes
          );
        }
      }

      if (successfulNodes.length) {
        items.push({
          name: stage.name,
          status: 'success',
          scope: {
            type: 'node',
            nodes: [
              ...new Set(
                successfulNodes
              ),
            ],
          },
        });
      }

      for (
        const [
          errorMessage,
          nodes,
        ] of failures
      ) {
        items.push({
          name: stage.name,
          status: 'failure',
          scope: {
            type: 'node',
            nodes: [
              ...new Set(nodes),
            ],
          },
          errorMessage,
        });
      }
    }

    return items;
  }
}