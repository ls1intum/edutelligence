import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TeamActivityService } from './activity-tab.service';
import { TraceExport, TraceExportItem } from './activity-tab.models';
import { ActivityTabComponent, TRACE_CSV_COLUMNS, traceCsvCell, tracesToCsv } from './activity-tab';

// ── CSV building ─────────────────────────────────────────────────────────────

describe('traceCsvCell', () => {
  it('leaves absent values empty', () => {
    expect(traceCsvCell(null)).toBe('');
    expect(traceCsvCell(undefined)).toBe('');
  });

  it('keeps plain values bare', () => {
    expect(traceCsvCell('req-aaa-111')).toBe('req-aaa-111');
    expect(traceCsvCell(42)).toBe('42');
    expect(traceCsvCell(true)).toBe('true');
  });

  it('quotes and doubles what would break a table', () => {
    expect(traceCsvCell('failed, timeout')).toBe('"failed, timeout"');
    expect(traceCsvCell('say "hi"')).toBe('"say ""hi"""');
    expect(traceCsvCell('line\nbreak')).toBe('"line\nbreak"');
  });

  it('sends structured values out as compact JSON, quoted', () => {
    expect(traceCsvCell({ model: 'gpt-4' })).toBe('"{""model"":""gpt-4""}"');
    // A payload full of commas and quotes must stay one cell: the value is
    // JSON-compacted first, then every quote is doubled — the inner quotes of
    // the content survive as JSON escapes, each of them doubled like the rest.
    const raw = JSON.stringify({ content: 'Hello, "Logos"' });
    expect(traceCsvCell({ content: 'Hello, "Logos"' })).toBe(
      `"${raw.replaceAll('"', '""')}"`,
    );
  });
});

describe('tracesToCsv', () => {
  const trace: TraceExportItem = {
    request_id: 'req-ccc-333',
    timestamp_request: null,
    timestamp_forwarding: null,
    timestamp_response: null,
    time_at_first_token: null,
    privacy_level: 'FULL',
    model_name: null,
    provider_name: null,
    provider_type: null,
    policy_id: null,
    environment: null,
    api_key_id: null,
    api_key_name: null,
    username: null,
    full_name: null,
    team_name: null,
    client_ip: null,
    status: 'success',
    error_message: 'failed, timeout "rare"',
    priority: null,
    initial_priority: null,
    priority_when_scheduled: null,
    queue_depth_at_enqueue: null,
    queue_depth_at_schedule: null,
    queue_depth_at_arrival: null,
    timeout_s: null,
    utilization_at_arrival: null,
    queue_wait_ms: null,
    was_cold_start: null,
    load_duration_ms: null,
    available_vram_mb: null,
    azure_rate_remaining_requests: null,
    azure_rate_remaining_tokens: null,
    prompt_tokens: null,
    completion_tokens: null,
    total_tokens: null,
    cost_microcents: null,
    classification_statistics: null,
    input_payload: { model: 'gpt-4', messages: [{ role: 'user', content: 'Hello, "Logos"' }] },
    headers: null,
    response_payload: null,
  };

  const payload: TraceExport = {
    team_id: 2001,
    team_name: 'test-team',
    days: 7,
    since: '2026-08-20T00:00:00Z',
    count: 1,
    truncated: false,
    traces: [trace],
  };

  it('writes the header from the same columns the JSON envelope carries', () => {
    const lines = tracesToCsv(payload).split('\n');
    expect(lines[0]).toBe(TRACE_CSV_COLUMNS.join(','));
    expect(lines).toHaveLength(2);
  });

  it('keeps one trace on one row with absent cells empty', () => {
    const lines = tracesToCsv(payload).split('\n');
    // request_id, then the four absent timestamps, then privacy_level —
    // the leading shape of the row says the empty cells stayed in place
    // rather than shifting the columns left.
    expect(lines[1].startsWith('req-ccc-333,,,,,FULL,')).toBe(true);
  });

  it('escapes cells the way traceCsvCell promises', () => {
    const csv = tracesToCsv(payload);
    expect(csv).toContain('"failed, timeout ""rare"""');
    // The payload cell goes out exactly as the cell builder spells it,
    // unsplit across the row.
    expect(csv).toContain(traceCsvCell(trace.input_payload));
  });
});

// ── The component's export flow ──────────────────────────────────────────────

describe('ActivityTabComponent trace export', () => {
  let fixture: ComponentFixture<ActivityTabComponent>;
  let component: ActivityTabComponent;
  let activityService: {
    getActivity: ReturnType<typeof vi.fn>;
    getTraceExport: ReturnType<typeof vi.fn>;
  };
  let lastBlob: Blob | null;
  let lastAnchor: HTMLAnchorElement | null;
  const payload: TraceExport = {
    team_id: 42,
    team_name: 'test-team',
    days: 7,
    since: '2026-08-20T00:00:00Z',
    count: 0,
    truncated: false,
    traces: [],
  };

  beforeEach(async () => {
    activityService = {
      getActivity: vi.fn().mockResolvedValue(null),
      getTraceExport: vi.fn().mockResolvedValue(payload),
    };
    lastBlob = null;
    lastAnchor = null;

    await TestBed.configureTestingModule({
      imports: [ActivityTabComponent],
      providers: [{ provide: TeamActivityService, useValue: activityService }],
    }).compileComponents();

    fixture = TestBed.createComponent(ActivityTabComponent);
    component = fixture.componentInstance;
    component.teamId = 42;
    fixture.detectChanges();

    vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
      lastBlob = blob as Blob;
      return 'blob:test';
    });
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      lastAnchor = this;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('asks the server for the team, the period and the active requester filter', async () => {
    component.filterUserId.set(7);

    await component.exportTraces();

    expect(activityService.getTraceExport).toHaveBeenCalledWith(42, 7, 7);
  });

  it('downloads the JSON envelope under a named file', async () => {
    await component.exportTraces();

    expect(lastAnchor?.download).toBe('logos-traces-team-42-7d.json');
    expect(lastBlob?.type).toBe('application/json');
    expect(await lastBlob?.text()).toBe(JSON.stringify(payload, null, 2));
  });

  it('cuts the CSV from the same envelope when the format asks for it', async () => {
    component.exportFormat.set('csv');

    await component.exportTraces();

    expect(lastAnchor?.download).toBe('logos-traces-team-42-7d.csv');
    expect(lastBlob?.type).toBe('text/csv');
    expect(await lastBlob?.text()).toBe(tracesToCsv(payload));
  });

  it('accepts only json and csv as export formats', () => {
    component.setExportFormat('yaml');
    expect(component.exportFormat()).toBe('json');
    component.setExportFormat('csv');
    expect(component.exportFormat()).toBe('csv');
  });

  it('reports a failed export instead of downloading nothing', async () => {
    activityService.getTraceExport.mockRejectedValue(new Error('boom'));

    await component.exportTraces();

    expect(component.exportError()).toBe('Could not export the traces.');
    expect(component.exporting()).toBe(false);
    expect(lastAnchor).toBeNull();
  });
});
