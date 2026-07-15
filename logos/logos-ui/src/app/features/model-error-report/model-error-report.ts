import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { ModelManagementService } from '../../core/services/model-management.service';
import { Model } from '../../shared/models/model.model';

import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';


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
      checklist: 'IceCold',
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


  'gemma-4': [
    {
      id: 1,
      process: 'Download',
      status: 'success',
      checklist: 'IceCold',
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
      checklist: 'Cold',
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



  readonly tabs: readonly ModelErrorTab[] = [
    'error_report',
    'complete_logs',
  ];


  readonly visibleTabs = computed<readonly ModelErrorTab[]>(() => this.tabs);



  readonly tabLabel: Record<ModelErrorTab, string> = {
    error_report: 'Error Report',
    complete_logs: 'Complete Logs',
  };



  readonly model = signal<Model | null>(null);

  readonly modelId = signal<number | null>(null);


  readonly loading = signal(true);

  readonly loadError = signal(false);



  readonly activeTab = signal<ModelErrorTab>(
    'error_report'
  );


  readonly processesLoading = signal(false);



  /**
   * User-controlled UI state.
   */
  readonly expandedProcess = signal<number[]>([]);



  /**
   * Derived process data based on current model.
   */
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



  getLifecycleEmoji(stage: string): string {

    const lifecycleEmoji: Record<string, string> = {

      DeepFreeze: '❄️',
      IceCold: '🧊',
      Cold: '🥶',
      WarmDisk: '💽',
      Lukewarm: '💧',
      Warm: '♨️',
      Hot: '🔥',
      Dusty: '🕸️',
      Dead: '☠️',

    };


    return lifecycleEmoji[stage] ?? '';

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

}