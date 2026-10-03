import { BenchmarkSettings, BenchmarkWorkerLimits, SERVING_FIELDS, servingValidationErrors } from './benchmark-settings';

export interface BatchConfiguration extends BenchmarkSettings { samples: number; }
export interface BenchmarkBatch { configurations: BatchConfiguration[]; repetitions: number; }
export interface Sweep { key: string; mode: 'values' | 'range'; values: string; start: number; end: number; step: number; }
export interface SweepField { key: string; label: string; type: string; min?: number; max?: number; step?: number; }
export const SWEEP_FIELDS: readonly SweepField[] = [
  { key: 'concurrency', label: 'Concurrent requests', type: 'number', min: 1, max: 32 },
  { key: 'max_output_tokens', label: 'Max output tokens', type: 'number', min: 1, max: 4096 },
  { key: 'samples', label: 'Sample size', type: 'number', min: 1, max: 100 },
  { key: 'seed', label: 'Seed', type: 'number', min: 0, max: 2147483647 },
  ...SERVING_FIELDS,
];
const isServing = (key: string) => SERVING_FIELDS.some(field => field.key === key);

export function sweepValues(sweep: Sweep): (string | number | boolean)[] {
  const field = SWEEP_FIELDS.find(field => field.key === sweep.key);
  if (!field) throw new Error('Choose a parameter.');
  let values: (string | number | boolean)[];
  if (sweep.mode === 'range') {
    const { start, end, step } = sweep;
    if (field.type !== 'number' || ![start, end, step].every(Number.isFinite) || step <= 0 || end < start)
      throw new Error(`${field.label}: use an increasing range and a positive step.`);
    const count = Math.floor((end - start) / step + 1e-9) + 1;
    if (count > 1000) throw new Error('Use at most 1,000 values per parameter.');
    values = Array.from({ length: count }, (_, i) => Number((start + i * step).toFixed(10)));
  } else {
    const parts = sweep.values.split(',').map(value => value.trim());
    if (parts.some(value => !value)) throw new Error(`${field.label}: enter comma-separated values.`);
    values = parts.map(value => field.type === 'number' ? Number(value)
      : field.type === 'boolean' ? value === 'true' ? true : value === 'false' ? false : value : value);
  }
  if (values.some(value => field.type === 'boolean' ? typeof value !== 'boolean'
    : field.type === 'number' ? typeof value !== 'number' || !Number.isFinite(value)
      || value < (field.min ?? 0) || value > (field.max ?? Infinity) || (!field.step && !Number.isInteger(value)) : false))
    throw new Error(`${field.label}: enter ${field.type === 'boolean' ? 'true or false' : `valid ${field.step ? 'numbers' : 'integers'} (${field.min ?? 0}–${field.max ?? 'no upper limit'})`}.`);
  return [...new Set(values)];
}

/** Expand combinations, never repetitions; every configuration starts from the same fixed draft. */
export function buildBatch(settings: BenchmarkSettings, samples: number, sweeps: readonly Sweep[], repetitions: number,
  limits: BenchmarkWorkerLimits | null, worker: boolean): BenchmarkBatch {
  if (!Number.isSafeInteger(repetitions) || repetitions < 1 || repetitions > 10000)
    throw new Error('Enter 1–10,000 repetitions per configuration.');
  if (new Set(sweeps.map(sweep => sweep.key)).size !== sweeps.length) throw new Error('Choose each parameter only once.');
  let configurations: BatchConfiguration[] = [{ ...structuredClone(settings), samples }];
  for (const sweep of sweeps) {
    if (!worker && isServing(sweep.key)) throw new Error('vLLM parameters require a Logos worker.');
    const values = sweepValues(sweep);
    if (configurations.length * values.length > 1000) throw new Error('Use at most 1,000 configurations per batch.');
    configurations = configurations.flatMap(configuration => values.map(value => {
      const next = structuredClone(configuration);
      if (isServing(sweep.key)) next.serving_overrides[sweep.key] = value;
      else Object.assign(next, { [sweep.key]: value });
      // A concurrency sweep uses one consistent load profile, including concurrency 1.
      if (sweep.key === 'concurrency') next.profile = 'concurrent';
      return next;
    }));
  }
  if (configurations.length * repetitions > 10000) throw new Error('Use at most 10,000 total runs per batch.');
  for (const configuration of configurations) {
    const errors = servingValidationErrors(configuration, limits);
    if (errors.length) throw new Error(errors[0]);
  }
  return { configurations, repetitions };
}

export function configurationValue(configuration: BatchConfiguration, key: string): unknown {
  return isServing(key) ? configuration.serving_overrides[key] : configuration[key as keyof BatchConfiguration];
}
