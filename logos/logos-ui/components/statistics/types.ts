export type RequestEventRow = {
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

export type RequestEventResponse = {
  stats?: RequestEventStats;
  bucketSeconds?: number;
  range?: { start: string; end: string };
  rows?: RequestEventRow[];
};

export type RequestEventStats = {
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
