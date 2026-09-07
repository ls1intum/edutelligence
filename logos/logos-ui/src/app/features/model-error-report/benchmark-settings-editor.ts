import { Component, computed, effect, inject, model, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ModelManagementService } from '../../core/services/model-management.service';
import { BenchmarkSettings, DatasetMetadata, DEFAULT_BENCHMARK_SETTINGS, SERVING_FIELDS } from './benchmark-settings';

@Component({
  selector: 'app-benchmark-settings-editor', standalone: true, imports: [FormsModule],
  templateUrl: './benchmark-settings-editor.html', styleUrl: './benchmark-settings-editor.scss',
})
export class BenchmarkSettingsEditor {
  private service = inject(ModelManagementService);
  readonly settings = model<BenchmarkSettings>({ ...DEFAULT_BENCHMARK_SETTINGS, serving_overrides: {} });
  readonly validChange = output<boolean>();
  readonly fields: readonly { key: string; label: string; type: string; min?: number; max?: number; step?: number }[] = SERVING_FIELDS;
  readonly query = signal('gsm8k');
  readonly results = signal<{ id: string }[]>([]);
  readonly metadata = signal<DatasetMetadata | null>(null);
  readonly loading = signal(false);
  readonly searching = signal(false);
  readonly error = signal<string | null>(null);
  readonly jsonError = signal<string | null>(null);
  private metadataVersion = 0;
  private searchVersion = 0;
  readonly subsets = computed(() => [...new Set(this.metadata()?.splits.map(s => s.subset) ?? [this.settings().subset])]);
  readonly splits = computed(() => this.metadata()?.splits.filter(s => s.subset === this.settings().subset).map(s => s.split) ?? [this.settings().split]);
  readonly columns = computed(() => this.metadata()?.text_columns ?? [this.settings().text_column]);
  readonly hfOverrides = computed(() => this.settings().serving_overrides['hf_overrides'] ? JSON.stringify(this.settings().serving_overrides['hf_overrides'], null, 2) : '');

  constructor() {
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
      this.validChange.emit(!this.loading() && !this.jsonError() && validNumbers
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

  update<K extends keyof BenchmarkSettings>(key: K, value: BenchmarkSettings[K]): void {
    this.settings.update(s => ({ ...s, [key]: value }));
  }

  async search(): Promise<void> {
    const query = this.query().trim();
    if (!query) return;
    const version = ++this.searchVersion;
    this.searching.set(true);
    this.error.set(null);
    try {
      const result = await this.service.searchBenchmarkDatasets(query);
      if (version === this.searchVersion) this.results.set(result.datasets);
    } catch { if (version === this.searchVersion) this.error.set('Could not search Hugging Face. Try again.'); }
    finally { if (version === this.searchVersion) this.searching.set(false); }
  }

  async inspectDataset(dataset: string, subset?: string, split?: string): Promise<void> {
    const version = ++this.metadataVersion;
    this.loading.set(true);
    this.error.set(null);
    try {
      const meta = await this.service.getBenchmarkDatasetMetadata(dataset, subset, split);
      if (version !== this.metadataVersion) return;
      this.metadata.set(meta);
      this.settings.update(s => ({ ...s, dataset: meta.dataset, subset: meta.subset, split: meta.split,
        text_column: meta.text_columns.includes(s.text_column) ? s.text_column
          : meta.text_columns.includes('question') ? 'question' : meta.text_columns[0] }));
      this.results.set([]);
    } catch (error: any) {
      if (version === this.metadataVersion) this.error.set(error?.error?.detail ?? error?.error?.error ?? 'Could not inspect this dataset. Choose a public dataset with a text column.');
    } finally { if (version === this.metadataVersion) this.loading.set(false); }
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
