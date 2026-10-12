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
      lanes: { tp: lane({ gpu_devices: '0,1', effective_gpu_devices: '0,1', effective_vram_mb: 80_000 }) },
    });
    for (const card of cmp.cards) {
      expect(card.segments[0].mb).toBe(40_000);
      expect(card.segments[0].shared).toBe(true);
      expect(card.otherMb).toBe(0);
    }
  });

  it('puts a lane without placement on the only GPU, and lists it as unplaced on several', () => {
    const noPlacement = lane({ gpu_devices: null, effective_gpu_devices: null });
    expect(create({ devices: [device(40_000)], lanes: { a: noPlacement } }).cards[0].segments.length).toBe(1);

    const multi = create({ devices: [device(40_000), device(0)], lanes: { a: noPlacement } });
    expect(multi.cards.every((c) => c.segments.length === 0)).toBe(true);
    expect(multi.unplacedLanes.map((l) => l.laneId)).toEqual(['a']);
  });

  it('reads "all" as every GPU of the worker', () => {
    const cmp = create({
      devices: [device(40_000), device(40_000)],
      lanes: { a: lane({ gpu_devices: 'all', effective_gpu_devices: 'all', effective_vram_mb: 80_000 }) },
    });
    expect(cmp.cards.map((c) => c.segments.length)).toEqual([1, 1]);
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
