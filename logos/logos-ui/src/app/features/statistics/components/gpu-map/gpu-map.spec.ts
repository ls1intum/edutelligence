import { TestBed } from '@angular/core/testing';

import { GpuMapComponent, parseGpuIndices } from './gpu-map';
import type { DeviceInfo, LaneSignalData } from '../../statistics.models';

const device = (used: number, total = 100_000): DeviceInfo => ({
  device_id: '0',
  kind: 'nvidia',
  name: 'GPU',
  memory_used_mb: used,
  memory_total_mb: total,
  memory_free_mb: total - used,
  utilization_percent: 10,
  temperature_celsius: 50,
  power_draw_watts: 100,
});

const lane = (over: Partial<LaneSignalData> = {}): LaneSignalData => ({
  model: 'org/model-a',
  runtime_state: 'running',
  sleep_state: null,
  gpu_devices: '0',
  effective_gpu_devices: '0',
  num_parallel: 1,
  active_requests: 0,
  effective_vram_mb: 40_000,
  gpu_cache_usage_percent: null,
  ttft_p95_seconds: null,
  queue_waiting: null,
  requests_running: null,
  prefix_cache_hit_rate: null,
  mtp_acceptance_rate: null,
  max_model_len: null,
  ...over,
});

describe('parseGpuIndices', () => {
  it('reads single indices, lists and ranges', () => {
    expect(parseGpuIndices('0')).toEqual([0]);
    expect(parseGpuIndices('0,1')).toEqual([0, 1]);
    expect(parseGpuIndices('0-2')).toEqual([0, 1, 2]);
    expect(parseGpuIndices('0, 2-3')).toEqual([0, 2, 3]);
  });

  it('names no GPU for anything it cannot read', () => {
    expect(parseGpuIndices(null)).toEqual([]);
    expect(parseGpuIndices('')).toEqual([]);
    expect(parseGpuIndices('GPU-abc')).toEqual([]);
    expect(parseGpuIndices('3-1')).toEqual([]);
    // Past 2^53 a counting loop cannot advance.
    expect(parseGpuIndices('9007199254740992')).toEqual([]);
  });
});

describe('GpuMapComponent', () => {
  function create(inputs: Partial<GpuMapComponent>): GpuMapComponent {
    const cmp = TestBed.createComponent(GpuMapComponent).componentInstance;
    Object.assign(cmp, inputs);
    return cmp;
  }

  it('draws one card per GPU with the lanes placed on it', () => {
    const cmp = create({
      devices: [device(50_000), device(10_000)],
      lanes: { a: lane(), b: lane({ model: 'org/model-b', gpu_devices: '1', effective_gpu_devices: '1', effective_vram_mb: 8_000, runtime_state: 'sleeping' }) },
    });
    const [gpu0, gpu1] = cmp.cards;
    expect(gpu0.segments.map((s) => s.laneId)).toEqual(['a']);
    expect(gpu1.segments.map((s) => s.laneId)).toEqual(['b']);
    expect(gpu1.segments[0].state).toBe('sleeping');
    expect(gpu0.otherMb).toBe(10_000);
    expect(gpu0.freeMb).toBe(50_000);
  });

  it('splits a tensor-parallel lane evenly across its cards', () => {
    const cmp = create({
      devices: [device(40_000), device(40_000)],
      lanes: {
        tp: lane({
          gpu_devices: '0,1',
          effective_gpu_devices: '0,1',
          occupied_gpu_devices: '0,1',
          effective_vram_mb: 80_000,
        }),
      },
    });
    for (const card of cmp.cards) {
      expect(card.segments[0].mb).toBe(40_000);
      expect(card.segments[0].shared).toBe(true);
      expect(card.otherMb).toBe(0);
    }
  });

  it('draws a lane only on the GPUs it occupies, not every GPU it can see', () => {
    // A TP=1 lane started with "1,0" runs on GPU 1 alone.
    const cmp = create({
      devices: [device(0), device(40_000)].map((d, i) => ({ ...d, index: i })),
      lanes: { a: lane({ gpu_devices: '1,0', effective_gpu_devices: '1,0', occupied_gpu_devices: '1' }) },
    });
    expect(cmp.cards.map((c) => c.segments.map((s) => [s.mb, s.shared]))).toEqual([[], [[40_000, false]]]);
  });

  it('leaves a lane unplaced when the worker does not know which GPUs it occupies', () => {
    const cmp = create({
      devices: [device(0), device(0)],
      lanes: { a: lane({ gpu_devices: '1,0', effective_gpu_devices: '1,0', occupied_gpu_devices: '' }) },
    });
    expect(cmp.cards.every((c) => c.segments.length === 0)).toBe(true);
    expect(cmp.unplacedLanes.map((l) => l.laneId)).toEqual(['a']);
  });

  it('lists a lane without placement as unplaced, even with one card reported', () => {
    const noPlacement = lane({ gpu_devices: null, effective_gpu_devices: null });
    const single = create({ devices: [device(40_000)], lanes: { a: noPlacement } });
    expect(single.cards[0].segments).toEqual([]);
    expect(single.unplacedLanes.map((l) => l.laneId)).toEqual(['a']);

    const multi = create({ devices: [device(40_000), device(0)], lanes: { a: noPlacement } });
    expect(multi.cards.every((c) => c.segments.length === 0)).toBe(true);
    expect(multi.unplacedLanes.map((l) => l.laneId)).toEqual(['a']);
  });

  it('leaves "all" unplaced on a worker with several GPUs', () => {
    // "all" is what the lane could see, not what it holds: a single-GPU lane
    // started that way sits on one card the worker does not name.
    const cmp = create({
      devices: [device(40_000), device(40_000)],
      lanes: { a: lane({ gpu_devices: 'all', effective_gpu_devices: 'all' }) },
    });
    expect(cmp.cards.map((c) => c.segments.length)).toEqual([0, 0]);
    expect(cmp.unplacedLanes.map((l) => l.laneId)).toEqual(['a']);
  });

  it('does not take the only reported card for the GPU of an unknown lane', () => {
    // GPU 0 dropped out of the report; the lane started with "all" may still
    // hold it, so drawing it on GPU 1 would be wrong.
    const cmp = create({
      devices: [{ ...device(40_000), device_id: 'GPU-1', index: 1 }],
      lanes: { a: lane({ gpu_devices: 'all', effective_gpu_devices: 'all', occupied_gpu_devices: '' }) },
    });
    expect(cmp.cards[0].segments).toEqual([]);
    expect(cmp.unplacedLanes.map((l) => l.laneId)).toEqual(['a']);
  });

  it('places "all" where the worker reports it from a complete inventory', () => {
    const cmp = create({
      devices: [device(40_000)],
      lanes: { a: lane({ gpu_devices: 'all', effective_gpu_devices: 'all', occupied_gpu_devices: '0' }) },
    });
    expect(cmp.cards[0].segments.map((s) => s.mb)).toEqual([40_000]);
    expect(cmp.unplacedLanes).toEqual([]);
  });

  it('draws every lane onto an aggregate pool at its full footprint', () => {
    const pool: DeviceInfo = { ...device(90_000, 200_000), device_id: 'aggregate', kind: 'derived' };
    const cmp = create({
      devices: [pool],
      lanes: {
        one: lane({ gpu_devices: '1', effective_gpu_devices: '1', effective_vram_mb: 30_000 }),
        tp: lane({ gpu_devices: '0,1', effective_gpu_devices: '0,1', effective_vram_mb: 60_000 }),
      },
    });
    expect(cmp.cards[0].pool).toBe(true);
    expect(cmp.cards[0].title).toBe('Memory pool');
    expect(cmp.cards[0].segments.map((s) => [s.laneId, s.mb])).toEqual([
      ['one', 30_000],
      ['tp', 60_000],
    ]);
    expect(cmp.unplacedLanes).toEqual([]);
  });

  it('orders lanes busiest state first', () => {
    const cmp = create({
      devices: [device(90_000)],
      lanes: {
        s: lane({ runtime_state: 'sleeping', effective_vram_mb: 10_000 }),
        r: lane({ runtime_state: 'running', effective_vram_mb: 10_000 }),
      },
    });
    expect(cmp.cards[0].segments.map((s) => s.laneId)).toEqual(['r', 's']);
  });

  it('draws no cards for unified memory, whose pool the donut shows', () => {
    expect(create({ devices: [device(1)], unified: true, lanes: { a: lane() } }).cards).toEqual([]);
  });

  it('names cards by the worker GPU index, not list position', () => {
    // GPU 0 was left out by the worker, so the list starts at GPU 1.
    const cmp = create({
      devices: [{ ...device(40_000), index: 1 }, { ...device(0), index: 2 }],
      lanes: { a: lane({ gpu_devices: '1', effective_gpu_devices: '1' }) },
    });
    expect(cmp.cards.map((c) => c.title)).toEqual(['GPU 1', 'GPU 2']);
    expect(cmp.cards.map((c) => c.segments.length)).toEqual([1, 0]);
    expect(cmp.unplacedLanes).toEqual([]);
  });

  it('marks a failed GPU and keeps its held memory as other used', () => {
    const cmp = create({
      devices: [
        { ...device(83_000), index: 0, health: 'faulted', health_reason: 'GPU requires reset' },
        { ...device(0), index: 1 },
      ],
      lanes: {},
    });
    expect(cmp.cards.map((c) => c.health)).toEqual(['faulted', 'ok']);
    expect(cmp.cards[0].healthReason).toBe('GPU requires reset');
    expect(cmp.cards[0].otherMb).toBe(83_000);
  });

  it('renders the failure on the card', () => {
    const fixture = TestBed.createComponent(GpuMapComponent);
    fixture.componentRef.setInput('devices', [
      { ...device(83_000), index: 0, health: 'faulted', health_reason: 'GPU requires reset' },
    ]);
    fixture.detectChanges();
    const card: HTMLElement = fixture.nativeElement.querySelector('.gpu-map__card');
    expect(card.classList).toContain('gpu-map__card--faulted');
    expect(card.textContent).toContain('GPU requires reset');
    expect(card.textContent).toContain('No lane is placed on this GPU');
  });
});
