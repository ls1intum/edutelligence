import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { AuthService } from '../../../core/auth/services/auth.service';
import { StatsWebsocketService, StatsWsConnectOptions } from './stats-websocket.service';

class Socket {
  static readonly OPEN = 1;
  static instances: Socket[] = [];
  readonly readyState = 1;
  readonly send = vi.fn();
  readonly close = vi.fn();
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: unknown;
  onerror: unknown;
  constructor() {
    Socket.instances.push(this);
  }
}

describe('statistics websocket feed filters', () => {
  let service: StatsWebsocketService;
  beforeEach(() => {
    vi.useFakeTimers();
    Socket.instances = [];
    vi.stubGlobal('WebSocket', Socket);
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { freshToken: vi.fn().mockResolvedValue('test-token') } },
      ],
    });
    service = TestBed.inject(StatsWebsocketService);
  });
  afterEach(() => {
    service.disconnect();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('sends selections and restores the latest filter after reconnect', async () => {
    const opts: StatsWsConnectOptions = {
      vramDayOffset: -1,
      timeline: { start: '2026-09-01T00:00:00Z', end: '2026-10-01T00:00:00Z', targetBuckets: 60 },
      handlers: {
        onVramInit: vi.fn(),
        onVramDelta: vi.fn(),
        onTimelineInit: vi.fn(),
        onStats: vi.fn(),
        onRequestsData: vi.fn(),
      },
    };
    service.connect(opts);
    await Promise.resolve();
    const socket = Socket.instances[0];
    socket.onopen!();
    service.setFeedFilters('running', [1, 2], [3, 4]);
    expect(JSON.parse(socket.send.mock.calls.at(-1)![0])).toEqual({
      action: 'set_feed_filters',
      status: 'running',
      model_ids: [1, 2],
      provider_ids: [3, 4],
    });
    socket.onclose!();
    service.setFeedFilters('finished', [2], [4]);
    await vi.advanceTimersByTimeAsync(2000);
    const reconnected = Socket.instances[1];
    reconnected.onopen!();
    expect(JSON.parse(reconnected.send.mock.calls[0][0])).toMatchObject({
      action: 'init',
      status: 'finished',
      model_ids: [2],
      provider_ids: [4],
    });
  });
});
