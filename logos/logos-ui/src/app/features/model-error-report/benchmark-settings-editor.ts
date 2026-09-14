import { Component, computed, DestroyRef, effect, ElementRef, inject, input, model, output, signal, viewChild } from '@angular/core';
import { ModelBenchmarkPair } from '../../shared/models/provider.model';
import { FormsModule } from '@angular/forms';
import { ModelManagementService } from '../../core/services/model-management.service';
import { benchmarkErrorMessage, BenchmarkSettings, BenchmarkWorkerLimits, SERVING_CHOICES, servingValidationErrors, DatasetMetadata, datasetViewerUrl, DEFAULT_BENCHMARK_SETTINGS, SERVING_FIELDS } from './benchmark-settings';

@Component({
  selector: 'app-benchmark-settings-editor', standalone: true, imports: [FormsModule],
  templateUrl: './benchmark-settings-editor.html', styleUrl: './benchmark-settings-editor.scss',
})
export class BenchmarkSettingsEditor {
  private service = inject(ModelManagementService);
  readonly settings = model<BenchmarkSettings>({ ...DEFAULT_BENCHMARK_SETTINGS, serving_overrides: {} });
  readonly pair = input<ModelBenchmarkPair | null>(null);
  readonly limits = signal<BenchmarkWorkerLimits | null>(null);
  readonly limitsLoading = signal(false);
  readonly limitsError = signal<string | null>(null);
  readonly choices = SERVING_CHOICES;
  readonly validationErrors = computed(() => servingValidationErrors(this.settings(), this.limits()));
  private limitsVersion = 0;
  private limitsPairId: number | null = null;
  readonly validChange = output<boolean>();
  readonly fields: readonly { key: string; label: string; type: string; min?: number; max?: number; step?: number }[] = SERVING_FIELDS;
  readonly query = signal('gsm8k');
  readonly pickerOpen = signal(false);
  readonly pickerToggle = viewChild<ElementRef<HTMLButtonElement>>('pickerToggle');
  readonly nextCursor = signal<string | null>(null);
  private searchTimer?: ReturnType<typeof setTimeout>;
  private hasSearched = false;
  private failedCursor: string | undefined;
  readonly searchError = signal<string | null>(null);
  private lastInspection: [string, string?, string?] | null = null;
  readonly results = signal<string[]>([]);
  private readonly loadedDatasets = signal<string[]>([]);
  private readonly datasetCache = new Map<string, DatasetMetadata>();
  readonly datasetOptions = computed(() => [...new Set([
    DEFAULT_BENCHMARK_SETTINGS.dataset, ...this.loadedDatasets(), ...this.results(),
  ])]);
  readonly metadata = signal<DatasetMetadata | null>(null);
  readonly loading = signal(false);
  readonly searching = signal(false);
  readonly error = signal<string | null>(null);
  readonly jsonError = signal<string | null>(null);
  readonly viewerUrl = computed(() => datasetViewerUrl(this.settings()));
  readonly previewColumns = computed(() => {
    const prompt = this.settings().text_column;
    return [prompt, ...(this.metadata()?.preview_columns ?? []).filter(column => column !== prompt)];
  });
  readonly previewMatchesSelection = computed(() => {
    const meta = this.metadata();
    const s = this.settings();
    return meta?.dataset === s.dataset && meta?.subset === s.subset && meta?.split === s.split;
  });
  private metadataVersion = 0;
  private searchVersion = 0;
  readonly subsets = computed(() => [...new Set(this.metadata()?.splits.map(s => s.subset) ?? [this.settings().subset])]);
  readonly splits = computed(() => this.metadata()?.splits.filter(s => s.subset === this.settings().subset).map(s => s.split) ?? [this.settings().split]);
  readonly columns = computed(() => this.metadata()?.text_columns ?? [this.settings().text_column]);
  readonly hfOverrides = computed(() => this.settings().serving_overrides['hf_overrides'] ? JSON.stringify(this.settings().serving_overrides['hf_overrides'], null, 2) : '');

  constructor() {
    inject(DestroyRef).onDestroy(() => {
      clearTimeout(this.searchTimer);
      ++this.searchVersion;
      ++this.metadataVersion;
      ++this.limitsVersion;
    });
    effect(() => {
      const pair = this.pair();
      const id = pair?.model_provider_id ?? null;
      if (id === this.limitsPairId) return;
      this.limitsPairId = id;
      void this.loadLimits(pair);
    });
    effect(() => {
      const s = this.settings();
      const integer = (n: number, min: number, max: number) => Number.isInteger(n) && n >= min && n <= max;
      const validNumbers = this.fields.every(field => {
        const value = s.serving_overrides[field.key];
        if (value == null || field.type !== 'number') return true;
        const n = Number(value);
        return Number.isFinite(n) && n >= (field.min ?? 0) && (field.max == null || n <= field.max)
          && (field.step != null || Number.isInteger(n));
      });
      this.validChange.emit(!this.loading() && !this.jsonError() && validNumbers && this.validationErrors().length === 0
        && integer(s.max_output_tokens, 1, 4096) && integer(s.concurrency, 1, 32) && integer(s.seed, 0, 2147483647)
        && Boolean(s.dataset && s.subset && s.split && s.text_column));
    });
    effect(() => {
      const s = this.settings();
      // A copied historical run may select a different dataset than the current picker.
      if (this.metadata()?.dataset !== s.dataset || this.metadata()?.subset !== s.subset || this.metadata()?.split !== s.split) {
        void this.inspectDataset(s.dataset, s.subset, s.split);
      }
    });
  }

  async loadLimits(pair = this.pair()): Promise<void> {
    const version = ++this.limitsVersion;
    this.limits.set(null);
    this.limitsError.set(null);
    this.limitsLoading.set(false);
    if (!pair || pair.provider_type !== 'logosnode') return;
    this.limitsLoading.set(true);
    try {
      const limits = await this.service.getBenchmarkWorkerLimits(pair.model_provider_id);
      if (version === this.limitsVersion) this.limits.set(limits);
    } catch (error: any) {
      if (version === this.limitsVersion) this.limitsError.set(benchmarkErrorMessage(error, 'Could not load worker limits.'));
    } finally {
      if (version === this.limitsVersion) this.limitsLoading.set(false);
    }
  }

  parallelOptions(key: string): number[] {
    const count = this.limits()?.gpu_count ?? 0;
    const otherKey = key === 'tensor_parallel_size' ? 'pipeline_parallel_size' : 'tensor_parallel_size';
    const other = Number(this.settings().serving_overrides[otherKey] ?? this.limits()?.current[otherKey] ?? 1);
    const max = Number.isInteger(other) && other > 0 ? Math.min(64, Math.floor(count / other)) : 0;
    return Array.from({ length: max }, (_, i) => i + 1);
  }

  update<K extends keyof BenchmarkSettings>(key: K, value: BenchmarkSettings[K]): void {
    this.settings.update(s => ({ ...s, [key]: value }));
  }

  toggleDatasetPicker(): void {
    this.pickerOpen.update(open => !open);
    if (this.pickerOpen() && !this.hasSearched) void this.search();
  }

  closeDatasetPicker(): void {
    this.pickerOpen.set(false);
    this.pickerToggle()?.nativeElement.focus();
  }

  async selectDataset(dataset: string): Promise<void> {
    if (await this.inspectDataset(dataset)) this.closeDatasetPicker();
  }

  setQuery(value: string): void {
    clearTimeout(this.searchTimer);
    this.query.set(value);
    ++this.searchVersion;
    this.results.set([]);
    this.nextCursor.set(null);
    this.searching.set(true);
    this.searchError.set(null);
    this.searchTimer = setTimeout(() => void this.search(), 300);
  }

  async search(cursor?: string): Promise<void> {
    clearTimeout(this.searchTimer);
    const version = ++this.searchVersion;
    this.hasSearched = true;
    this.failedCursor = cursor;
    this.searching.set(true);
    this.searchError.set(null);
    try {
      const result = await this.service.searchBenchmarkDatasets(this.query().trim() || 'gsm8k', cursor);
      if (version !== this.searchVersion) return;
      const ids = result.datasets.map(dataset => dataset.id);
      this.results.update(previous => cursor ? [...new Set([...previous, ...ids])] : ids);
      this.nextCursor.set(result.next_cursor ?? null);
    } catch {
      if (version === this.searchVersion) this.searchError.set('Could not load datasets. Try again.');
    } finally {
      if (version === this.searchVersion) this.searching.set(false);
    }
  }

  retrySearch(): void {
    void this.search(this.failedCursor);
  }

  async inspectDataset(dataset: string, subset?: string, split?: string): Promise<boolean> {
    this.lastInspection = [dataset, subset, split];
    const version = ++this.metadataVersion;
    this.loading.set(true);
    this.error.set(null);
    try {
      const cached = this.datasetCache.get(dataset);
      const meta = cached && (subset == null || cached.subset === subset) && (split == null || cached.split === split)
        ? cached : await this.service.getBenchmarkDatasetMetadata(dataset, subset, split);
      if (version !== this.metadataVersion) return false;
      this.datasetCache.set(dataset, meta);
      this.loadedDatasets.update(ids => ids.includes(dataset) ? ids : [...ids, dataset]);
      this.metadata.set(meta);
      this.settings.update(s => ({ ...s, dataset: meta.dataset, subset: meta.subset, split: meta.split,
        text_column: meta.text_columns.includes(s.text_column) ? s.text_column
          : meta.text_columns.includes('question') ? 'question' : meta.text_columns[0] }));
      return true;
    } catch (error: any) {
      if (version === this.metadataVersion) this.error.set(benchmarkErrorMessage(error, 'Could not inspect this dataset. Choose a public dataset with a text column.'));
      return false;
    } finally { if (version === this.metadataVersion) this.loading.set(false); }
  }

  async retryDataset(): Promise<void> {
    if (this.lastInspection && await this.inspectDataset(...this.lastInspection)) this.closeDatasetPicker();
  }

  onServingToggle(event: Event): void {
    if ((event.target as HTMLDetailsElement).open && !this.limitsLoading()) void this.loadLimits();
  }

  setServing(key: string, value: unknown): void {
    const overrides = { ...this.settings().serving_overrides };
    if (value === '' || value == null) delete overrides[key];
    else overrides[key] = this.fields.find(field => field.key === key)?.type === 'number' ? Number(value) : value;
    this.update('serving_overrides', overrides);
  }

  setHfOverrides(text: string): void {
    try {
      const value = text.trim() ? JSON.parse(text) : null;
      if (value !== null && (typeof value !== 'object' || Array.isArray(value))) throw new Error();
      this.jsonError.set(null);
      this.setServing('hf_overrides', value);
    } catch { this.jsonError.set('Hugging Face overrides must be a JSON object.'); }
  }
}
