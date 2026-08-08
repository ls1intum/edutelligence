import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
  effect,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { ModelManagementService } from '../../core/services/model-management.service';
import { Model } from '../../shared/models/model.model';

import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';


type ModelErrorTab = 'error_report' | 'complete_logs';


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


interface ModelProcess {
  readonly id: number;
  readonly process: string;
  readonly status: 'success' | 'failure';
  readonly checklist: string;
  readonly items: readonly ChecklistItem[];
}


const PROCESS_DATA: Record<string, readonly ModelProcess[]> = {

  'gpt-mini': [
    {
      id: 1,
      process: 'Download',
      status: 'failure',
      checklist: 'Download',
      items: [
        {
          name: 'Model Identification',
          status: 'failure',
          scope: {
            type: 'global',
          },
          errorMessage:
            'Repository "gpt-mini/foo" does not exist.',
        },
      ],
    },
  ],


  'google__gemma-3-4b-it': [
    {
      id: 1,
      process: 'Download',
      status: 'success',
      checklist: 'Download',
      items: [
        {
          name: 'Model Identification',
          status: 'success',
        },
        {
          name: 'Model Download',
          status: 'success',
        },
      ],
    },

    {
      id: 2,
      process: 'Initialization',
      status: 'failure',
      checklist: 'Initialization',
      items: [
        {
          name: 'Initialized vLLM engine',
          status: 'success',
        },
        {
          name: 'Downloaded Weights',
          status: 'success',
        },
        {
          name: 'Loaded Safetensor Checkpoints',
          status: 'success',
        },
        {
          name: 'Loaded Weights',
          status: 'success',
        },
        {
          name: 'Loaded Model',
          status: 'success',
        },
        {
          name: 'Completed Warmup Run',
          status: 'success',
        },
        {
          name: 'Reserved KV-Cache Memory',
          status: 'success',
        },
        {
          name: 'Engine Core Started',
          status: 'failure',
          scope: {
            type: 'node',
            nodes: ['Node 3'],
          },
          errorMessage:
            'ValueError: To serve at least one request with the models max seq len (131072), KV cache memory is insufficient.',
        },
      ],
    },
  ],

};

const AVAILABLE_LOGS = [
  'google__gemma-3-4b-it',
];

interface ModelLog {
  readonly node: string;
  readonly file: string;
}

const MODEL_LOGS: Record<string, readonly ModelLog[]> = {

  'google__gemma-3-4b-it': [
    {
      node: 'Node 1',
      file: 'google__gemma-3-4b-it-node1.log',
    },
    {
      node: 'Node 3',
      file: 'google__gemma-3-4b-it-node3.log',
    },
  ],

};

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

  private readonly modelService = inject(ModelManagementService);

  private readonly http = inject(HttpClient);



  readonly tabs: readonly ModelErrorTab[] = [
    'error_report',
    'complete_logs',
  ];


  readonly visibleTabs = computed<readonly ModelErrorTab[]>(() => {

    if (this.hasCompleteLogs()) {
      return this.tabs;
    }

    return ['error_report'];

  });



  readonly tabLabel: Record<ModelErrorTab, string> = {
    error_report: 'Error Report',
    complete_logs: 'Complete Logs',
  };



  readonly model = signal<Model | null>(null);

  readonly modelId = signal<number | null>(null);


  readonly loading = signal(true);

  readonly loadError = signal(false);

  readonly completeLog = signal('');

  readonly hasCompleteLogs = computed(() => {

    const currentModel = this.model();

    if (!currentModel) {
      return false;
    }

    return AVAILABLE_LOGS.includes(
      currentModel.name
    );

  });

  readonly selectedLogNode = signal<string | null>(null);

  readonly availableLogs = computed(() => {

    const currentModel = this.model();

    if (!currentModel) {
      return [];
    }

    return MODEL_LOGS[currentModel.name] ?? [];

  });


  readonly selectedLog = computed(() => {

    const logs = this.availableLogs();

    if (!logs.length) {
      return null;
    }

    const selectedNode = this.selectedLogNode();

    return (
      logs.find(log =>
        log.node === selectedNode
      )
      ?? logs[0]
    );

  });

  constructor() {

    effect(() => {

      const log = this.selectedLog();

      if (!log) {
        return;
      }

      void this.loadLog(log.file);

    });

  }

  readonly activeTab = signal<ModelErrorTab>(
    'error_report'
  );

  readonly processesLoading = signal(false);

  readonly expandedProcess = signal<number[]>([]);

  readonly processes = computed<readonly ModelProcess[]>(() => {

    const currentModel = this.model();

    if (!currentModel) {
      return [];
    }


    return PROCESS_DATA[currentModel.name] ?? [];

  });

  readonly currentLifecycle = signal('IceCold');



  async ngOnInit(): Promise<void> {

    const id = Number(
      this.route.snapshot.paramMap.get('id')
    );


    this.modelId.set(id);

    await this.fetchModel(id);

  }



  async fetchModel(id: number): Promise<void> {

    this.loading.set(true);
    this.loadError.set(false);


    try {

      const models = await this.modelService.getModels();


      const foundModel = models.find(
        model => model.id === id
      );


      if (!foundModel) {

        this.loadError.set(true);
        return;

      }


      this.model.set(foundModel);

      const logs = MODEL_LOGS[foundModel.name];

      if (logs?.length) {
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


      return [
        ...current,
        id,
      ];

    });

  }



  isExpanded(id: number): boolean {

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

  getScopeLabel(scope?: ErrorScope): string {

    if (!scope) {
      return '';
    }


    if (scope.type === 'global') {
      return 'Global';
    }


    return scope.nodes?.join(', ') ?? '';

  }

  private async loadLog(file: string): Promise<void> {

    try {

      const log = await firstValueFrom(
        this.http.get(
          `/logs/${file}`,
          {
            responseType: 'text',
          }
        )
      );

      this.completeLog.set(log);

    } catch {

      this.completeLog.set(
        'Unable to load log file.'
      );

    }

  }

}