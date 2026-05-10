export type RequestLogRow = {
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

export type RequestLogResponse = {
  stats?: RequestLogStats;
  bucketSeconds?: number;
  range?: { start: string; end: string };
  rows?: RequestLogRow[];
};

export type RequestLogStats = {
  lastEventTs: string | null;
  totals: {
    requests: number;
    cloudRequests: number;
    localRequests: number;
    coldStarts: number;
    warmStarts: number;
    avgQueueSeconds: number | null;
    avgRunSeconds: number | null;
  };
  statusCounts: Record<string, number>;
  modelBreakdown: Array<{
    modelId: number;
    modelName: string;
    providerName: string;
    requestCount: number;
    avgQueueSeconds: number | null;
    avgRunSeconds: number | null;
    coldStarts: number;
    warmStarts: number;
    errorCount: number;
  }>;
  timeSeries: Array<{
    timestamp: number; // Unix ts
    label: string;
    cloud: number;
    local: number;
    total: number;
    avgRunSeconds: number | null;
    avgVram: number | null;
  }>;
  modelTimeSeries?: Array<{
    timestamp: number; // Unix ts (ms)
    modelId: number;
    modelName: string;
    count: number;
  }>;
  queueDepth: {
    avgEnqueueDepth: number | null;
    avgScheduleDepth: number | null;
    p95EnqueueDepth: number | null;
    p95ScheduleDepth: number | null;
  } | null;
  runtimeByColdStart: Array<{
    type: "cold" | "warm";
    avgRunSeconds: number | null;
    count: number;
  }>;
};

export type SelectionState = {
  start: number;
  end: number;
  active: boolean;
  pageX?: number;
  confirmable?: boolean;
};

/** Per-physical-GPU data from scheduler_signals.provider.devices[] */
export type DeviceInfo = {
  device_id: string;
  kind: "nvidia" | "derived";
  name: string;
  memory_used_mb: number;
  memory_total_mb: number;
  memory_free_mb: number;
  utilization_percent: number | null;
  temperature_celsius: number | null;
  power_draw_watts: number | null;
};

/** Per-lane signal data from scheduler_signals.lanes[lane_id] */
export type LaneSignalData = {
  model: string;
  vllm: boolean;
  runtime_state: string; // "running"|"loaded"|"sleeping"|"starting"|"cold"|"stopped"|"error"
  sleep_state: string | null;
  active_requests: number;
  effective_vram_mb: number;
  gpu_cache_usage_percent: number | null;
  ttft_p95_seconds: number | null;
  queue_waiting: number | null;
  requests_running: number | null;
};

/** Response from POST /logosdb/paginated_requests */
export type PaginatedRequestItem = {
  request_id: string;
  model_name: string;
  provider_name: string;
  is_cloud: boolean;
  status: string;
  timestamp: string | null;
  duration: number | null;
  cold_start: boolean | null;
  enqueue_ts: string | null;
  scheduled_ts: string | null;
  request_complete_ts: string | null;
  queue_seconds: number | null;
  total_seconds: number | null;
  initial_priority: string | null;
  priority_when_scheduled: string | null;
  queue_depth_at_enqueue: number | null;
  error_message: string | null;
};

export type PaginatedRequestResponse = {
  requests: PaginatedRequestItem[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
};
