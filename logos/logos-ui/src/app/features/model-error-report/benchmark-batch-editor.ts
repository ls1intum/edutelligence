import { Component, computed, effect, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BenchmarkSettings, BenchmarkWorkerLimits } from './benchmark-settings';
import { BenchmarkBatch, buildBatch, configurationValue, SWEEP_FIELDS, Sweep } from './benchmark-batch';

@Component({
  selector: 'app-benchmark-batch-editor', standalone: true, imports: [FormsModule],
  templateUrl: './benchmark-batch-editor.html', styleUrl: './benchmark-batch-editor.scss',
})
export class BenchmarkBatchEditor {
  readonly settings = input.required<BenchmarkSettings>();
  readonly samples = input.required<number>();
  readonly worker = input(false);
  readonly limits = input<BenchmarkWorkerLimits | null>(null);
  readonly planChange = output<BenchmarkBatch | null>();
  readonly enabled = signal(false);
  readonly repetitions = signal(3);
  readonly sweeps = signal<Sweep[]>([]);
  readonly previewLimit = signal(20);
  readonly fields = computed(() => SWEEP_FIELDS.filter(field => this.worker() || ['concurrency', 'samples', 'seed', 'max_output_tokens'].includes(field.key)));
  readonly available = computed(() => this.fields().filter(field => !this.sweeps().some(sweep => sweep.key === field.key)));
  readonly plan = computed(() => {
    if (!this.enabled()) return { batch: null, error: null };
    try { return { batch: buildBatch(this.settings(), this.samples(), this.sweeps(), this.repetitions(), this.limits(), this.worker()), error: null }; }
    catch (error) { return { batch: null, error: (error as Error).message }; }
  });
  readonly fixed = computed(() => {
    const configuration = { ...this.settings(), samples: this.samples() };
    return this.fields().filter(field => !this.sweeps().some(sweep => sweep.key === field.key)).map(field => ({
      label: field.label, value: configurationValue(configuration, field.key) ?? this.limits()?.current[field.key] ?? 'Current worker setting',
    }));
  });
  readonly validChange = output<boolean>();
  readonly value = configurationValue;
  constructor() {
    effect(() => { this.planChange.emit(this.plan().batch); this.validChange.emit(!this.plan().error); });
  }
  field(key: string) { return SWEEP_FIELDS.find(field => field.key === key)!; }
  add(key: string) {
    if (!key) return;
    const field = this.field(key);
    const current = configurationValue({ ...this.settings(), samples: this.samples() }, key) ?? this.limits()?.current[key];
    const value = current ?? (field.type === 'boolean' ? false : field.type === 'number' ? field.min ?? 1 : 'auto');
    this.sweeps.update(sweeps => [...sweeps, { key, mode: 'values', values: String(value), start: Number(value), end: Number(value), step: field.step ?? 1 }]);
  }
  update(index: number, patch: Partial<Sweep>) { this.sweeps.update(sweeps => sweeps.map((sweep, i) => i === index ? { ...sweep, ...patch } : sweep)); }
  remove(index: number) { this.sweeps.update(sweeps => sweeps.filter((_, i) => i !== index)); }
}
