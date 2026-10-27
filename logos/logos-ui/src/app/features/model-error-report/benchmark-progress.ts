import { ModelProviderBenchmark } from '../../shared/models/provider.model';
import { comparisonValue } from './benchmark-comparison';
import { batchingSignature, comparisonSettings } from './benchmark-isolation';

interface ProgressPoint {
  run: ModelProviderBenchmark;
  time: number;
  gain: number;
}

/** One best completed variant per baseline, separated by captured test conditions. */
export function benchmarkProgress(runs: readonly ModelProviderBenchmark[]) {
  const byId = new Map(runs.map(run => [run.id, run]));
  const groups = new Map<string, { reference: ModelProviderBenchmark; points: Map<number, ProgressPoint> }>();
  for (const run of runs) {
    const baselineId = (run.configuration['nightly'] as { baseline_id?: number } | undefined)?.baseline_id;
    const baseline = baselineId === undefined ? undefined : byId.get(baselineId);
    if (!baseline || baseline.id === run.id) continue;
    const key = batchingSignature(run);
    if (key === null || key !== batchingSignature(baseline)) continue;
    const before = comparisonValue(baseline, 'throughput');
    const after = comparisonValue(run, 'throughput');
    const ended = (run.configuration['measurement'] as { ended_at?: string } | undefined)?.ended_at;
    const time = ended ? Date.parse(ended) : NaN;
    if (before === null || before <= 0 || after === null || !Number.isFinite(time)) continue;
    const gain = (after / before - 1) * 100;
    if (!Number.isFinite(gain)) continue;
    const group = groups.get(key) ?? { reference: baseline, points: new Map<number, ProgressPoint>() };
    const previous = group.points.get(baseline.id);
    if (!previous || gain > previous.gain || (gain === previous.gain && run.id > previous.run.id)) {
      group.points.set(baseline.id, { run, time, gain });
    }
    groups.set(key, group);
  }
  return [...groups.entries()].map(([key, group]) => {
    const points = [...group.points.values()].sort((a, b) => a.time - b.time || a.run.id - b.run.id);
    const first = points[0].time, last = points[points.length - 1].time;
    const low = Math.min(0, ...points.map(point => point.gain));
    const high = Math.max(0, ...points.map(point => point.gain));
    const padding = Math.max(1, (high - low) * .15);
    const min = low - padding, max = high + padding;
    const y = (gain: number) => (max - gain) / (max - min) * 100;
    const plotted = points.map(point => ({ ...point,
      x: first === last ? 50 : (point.time - first) / (last - first) * 100, y: y(point.gain) }));
    const settings = comparisonSettings(group.reference);
    return { key, first, last, min, max, zero: y(0), points: plotted,
      line: plotted.map(point => `${point.x},${point.y}`).join(' '),
      label: `${group.reference.provider_name} · ${group.reference.dataset} · #${group.reference.id}`,
      context: `${group.reference.provider_name} · ${group.reference.dataset} · ${settings['max_concurrency']} parallel · ≤${settings['max_output_tokens']} output tokens · ${group.reference.sample_size} requests`,
    };
  }).sort((a, b) => b.last - a.last);
}
