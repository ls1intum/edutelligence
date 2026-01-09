type RequestEventRow = {
  request_id: string;
  model_id: number | null;
  provider_id: number | null;
  initial_priority: string | null;
  priority_when_scheduled: string | null;
  queue_depth_at_enqueue: number | null;
  queue_depth_at_schedule: number | null;
  timeout_s: number | null;
  enqueue_ts: string | null;
  scheduled_ts: string | null;
  request_complete_ts: string | null;
  available_vram_mb: number | null;
  azure_rate_remaining_requests: number | null;
  azure_rate_remaining_tokens: number | null;
  cold_start: boolean | null;
  result_status: string | null;
  error_message: string | null;
};

const BASE_MOCK_ROWS: RequestEventRow[] = [
  {
    request_id: "seed-1",
    model_id: 10,
    provider_id: 2,
    initial_priority: "normal",
    priority_when_scheduled: "normal",
    queue_depth_at_enqueue: 0,
    queue_depth_at_schedule: 0,
    timeout_s: null,
    enqueue_ts: "2025-12-28T20:31:42.957755+00:00",
    scheduled_ts: "2025-12-28T20:31:42.982784+00:00",
    request_complete_ts: "2025-12-28T20:31:50.800739+00:00",
    available_vram_mb: null,
    azure_rate_remaining_requests: 999,
    azure_rate_remaining_tokens: 999988,
    cold_start: false,
    result_status: "success",
    error_message: null,
  },
  {
    request_id: "seed-2",
    model_id: 15,
    provider_id: 6,
    initial_priority: "normal",
    priority_when_scheduled: "normal",
    queue_depth_at_enqueue: 0,
    queue_depth_at_schedule: 0,
    timeout_s: null,
    enqueue_ts: "2025-12-28T20:34:23.502786+00:00",
    scheduled_ts: "2025-12-28T20:34:23.650881+00:00",
    request_complete_ts: "2025-12-28T20:34:46.176515+00:00",
    available_vram_mb: 12500,
    azure_rate_remaining_requests: null,
    azure_rate_remaining_tokens: null,
    cold_start: true,
    result_status: "success",
    error_message: null,
  },
  {
    request_id: "seed-3",
    model_id: 14,
    provider_id: 6,
    initial_priority: "normal",
    priority_when_scheduled: "normal",
    queue_depth_at_enqueue: 0,
    queue_depth_at_schedule: 0,
    timeout_s: null,
    enqueue_ts: "2025-12-28T20:32:11.733902+00:00",
    scheduled_ts: "2025-12-28T20:32:11.875745+00:00",
    request_complete_ts: "2025-12-28T20:32:42.000098+00:00",
    available_vram_mb: 12500,
    azure_rate_remaining_requests: null,
    azure_rate_remaining_tokens: null,
    cold_start: false,
    result_status: "error",
    error_message: "",
  },
  {
    request_id: "seed-4",
    model_id: 33,
    provider_id: 6,
    initial_priority: "normal",
    priority_when_scheduled: "normal",
    queue_depth_at_enqueue: 0,
    queue_depth_at_schedule: 0,
    timeout_s: null,
    enqueue_ts: "2025-12-28T20:24:15.047690+00:00",
    scheduled_ts: "2025-12-28T20:24:15.191829+00:00",
    request_complete_ts: "2025-12-28T20:24:44.455808+00:00",
    available_vram_mb: 12500,
    azure_rate_remaining_requests: null,
    azure_rate_remaining_tokens: null,
    cold_start: false,
    result_status: "success",
    error_message: null,
  },
  {
    request_id: "seed-5",
    model_id: 23,
    provider_id: 2,
    initial_priority: "normal",
    priority_when_scheduled: "normal",
    queue_depth_at_enqueue: 0,
    queue_depth_at_schedule: 0,
    timeout_s: null,
    enqueue_ts: "2025-12-28T20:25:29.251006+00:00",
    scheduled_ts: "2025-12-28T20:25:29.281297+00:00",
    request_complete_ts: "2025-12-28T20:25:34.007126+00:00",
    available_vram_mb: null,
    azure_rate_remaining_requests: 999,
    azure_rate_remaining_tokens: 999996,
    cold_start: false,
    result_status: "success",
    error_message: null,
  },
];

export const buildMockRows = (
  count: number,
  daysBack: number = 30
): RequestEventRow[] => {
  const rows: RequestEventRow[] = [];
  const now = Date.now();
  const start = now - daysBack * 24 * 60 * 60 * 1000;

  const uuidish = (i: number) => {
    const hex = (n: number, len = 4) => n.toString(16).padStart(len, "0");
    return `${hex(i, 8)}-${hex(i * 3)}-${hex(i * 5)}-${hex(i * 7)}-${hex(
      i * 11
    )}${hex(i * 13, 8)}`;
  };

  for (let i = 0; i < count; i++) {
    const base = BASE_MOCK_ROWS[i % BASE_MOCK_ROWS.length];
    // Random distribution over the time range, favoring more recent times slightly
    const randomOffset = Math.random() * (daysBack * 24 * 60 * 60 * 1000);
    const time = start + randomOffset;

    const enqueue = new Date(time);
    const scheduled = new Date(enqueue.getTime() + 50 + Math.random() * 500); // 50-550ms queue
    const complete = new Date(
      scheduled.getTime() + 1000 + Math.random() * 20000
    ); // 1-21s run

    const isCold = Math.random() < 0.2 ? true : base.cold_start; // 20% cold chance
    const failChance = Math.random();
    const status =
      failChance < 0.05 ? "error" : failChance < 0.08 ? "failed" : "success";

    // VRAM simulation: fluctuaties over time + random noise
    // Sine wave pattern for "load"
    const hour = enqueue.getHours();
    const loadFactor = (Math.sin(hour / 3) + 1) / 2; // 0 to 1
    const availableVram = 8000 + loadFactor * 16000 + Math.random() * 2000;

    const enqueueDepth = Math.floor(Math.random() * 5) + (hour > 12 ? 2 : 0);
    const scheduleDepth = Math.floor(Math.random() * 5);

    rows.push({
      request_id: uuidish(i + 1),
      model_id: base.model_id,
      provider_id: Math.random() > 0.6 ? 2 : 6, // 40% cloud (2), 60% local (6)
      initial_priority: base.initial_priority,
      priority_when_scheduled: base.priority_when_scheduled,
      queue_depth_at_enqueue: enqueueDepth,
      queue_depth_at_schedule: scheduleDepth,
      timeout_s: base.timeout_s,
      enqueue_ts: enqueue.toISOString(),
      scheduled_ts: scheduled.toISOString(),
      request_complete_ts: complete.toISOString(),
      available_vram_mb: availableVram,
      azure_rate_remaining_requests:
        base.provider_id === 2 ? 900 - (i % 10) * 5 : null,
      azure_rate_remaining_tokens:
        base.provider_id === 2 ? 900000 - (i % 20) * 1000 : null,
      cold_start: isCold,
      result_status: status,
      error_message:
        status !== "success"
          ? status === "failed"
            ? "provider timeout"
            : "error"
          : null,
    });
  }
  // Sort by enqueue time
  return rows.sort(
    (a, b) =>
      new Date(a.enqueue_ts!).getTime() - new Date(b.enqueue_ts!).getTime()
  );
};

export const MAX_MOCK_ROWS = 2000;
