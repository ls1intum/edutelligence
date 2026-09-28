import { TestBed } from '@angular/core/testing';

import { LaneMemoryPieComponent } from './lane-memory-pie';
import type { LaneSignalData } from '../../statistics.models';

const lane = (partial: Partial<LaneSignalData>): LaneSignalData => ({
  model: 'org/model',
  runtime_state: 'loaded',
  sleep_state: null,
  gpu_devices: null,
  effective_gpu_devices: null,
  num_parallel: null,
  active_requests: 0,
  effective_vram_mb: 0,
  gpu_cache_usage_percent: null,
  ttft_p95_seconds: null,
  queue_waiting: null,
  requests_running: null,
  prefix_cache_hit_rate: null,
  mtp_acceptance_rate: null,
  max_model_len: null,
  ...partial,
});

async function pie(inputs: Partial<LaneMemoryPieComponent>): Promise<LaneMemoryPieComponent> {
  await TestBed.configureTestingModule({
    imports: [LaneMemoryPieComponent],
  }).compileComponents();
  const fixture = TestBed.createComponent(LaneMemoryPieComponent);
  Object.assign(fixture.componentInstance, inputs);
  return fixture.componentInstance;
}

/**
 * The 'unified' metric is the pie a single-pool machine (Apple Silicon) gets
 * instead of a VRAM pie next to a RAM pie. The pool figures come from the
 * host's memory summary, but the per-lane slices are the lanes' model
 * footprints — on unified memory the weights live in the pool, and per-lane
 * host RAM is not measured there.
 */
describe('LaneMemoryPieComponent unified metric', () => {
  it('breaks the single pool down by the lanes model footprints', async () => {
    const comp = await pie({
      metric: 'unified',
      lanes: {
        a: lane({ model: 'org/big', effective_vram_mb: 8_192 }),
        b: lane({ model: 'org/small', effective_vram_mb: 2_048 }),
      },
      totalMb: 32_768,
      freeMb: 12_288,
    });

    const slices = comp.slices;
    // 8 GB and 2 GB of lane weights, the 10 GB the rest of the system holds,
    // and the 12 GB still free — the whole 32 GB pool, once.
    expect(slices.map((s) => s.text)).toEqual([
      'big · a [loaded]',
      'small · b [loaded]',
      'Other used',
      'Free',
    ]);
    expect(slices.reduce((sum, s) => sum + s.value, 0)).toBeCloseTo(32, 3);
  });

  it('slices by the model footprint, not the unmeasured per-lane host RAM', async () => {
    const comp = await pie({
      metric: 'unified',
      lanes: { a: lane({ model: 'org/model', effective_vram_mb: 1_024, host_ram_mb: 64 }) },
      totalMb: 16_384,
      freeMb: 15_360,
    });

    const laneSlice = comp.slices.find((s) => s.text.startsWith('model ·'));
    expect(laneSlice?.value).toBeCloseTo(1, 3);
  });

  it('reads its empty state as plain memory, not VRAM or RAM', async () => {
    const comp = await pie({ metric: 'unified', lanes: {}, totalMb: 0, freeMb: 0 });
    expect(comp.emptyMessage).toBe('No memory data available');
  });
});
