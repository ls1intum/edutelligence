// RequestLogRow from logos-ui-old/components/statistics/types.ts
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

// RequestLogResponse from logos-ui-old/components/statistics/types.ts
export type RequestLogResponse = {
  stats?: RequestLogStats;
  bucketSeconds?: number;
  range?: { start: string; end: string };
  rows?: RequestLogRow[];
};

// RequestLogStats from logos-ui-old/components/statistics/types.ts
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

// SelectionState from logos-ui-old/components/statistics/types.ts
export type SelectionState = {
  start: number;
  end: number;
  active: boolean;
  pageX?: number;
  confirmable?: boolean;
};

// DeviceInfo from logos-ui-old/components/statistics/types.ts
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

// LaneSignalData from logos-ui-old/components/statistics/types.ts
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

// PaginatedRequestItem from logos-ui-old/components/statistics/types.ts
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

// PaginatedRequestResponse from logos-ui-old/components/statistics/types.ts
export type PaginatedRequestResponse = {
  requests: PaginatedRequestItem[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
};

// VramV2Sample from logos-ui-old/hooks/use-stats-websocket-v2.ts
export interface VramV2Sample {
  snapshot_id?: number;
  timestamp: string;
  vram_mb?: number;
  used_vram_mb?: number;
  remaining_vram_mb?: number;
  total_vram_mb?: number;
  loaded_models?: Array<any>;
  scheduler_signals?: {
    provider?: {
      device_mode?: string;
      nvidia_smi_available?: boolean;
      device_count?: number;
      total_memory_mb?: number;
      used_memory_mb?: number;
      free_memory_mb?: number;
      lane_count?: number;
      active_requests?: number;
      loaded_lane_count?: number;
      sleeping_lane_count?: number;
      cold_lane_count?: number;
      total_effective_vram_mb?: number;
      devices?: DeviceInfo[];
    };
    lanes?: Record<string, LaneSignalData>;
    models?: Record<string, any>;
  };
}

// VramV2Provider from logos-ui-old/hooks/use-stats-websocket-v2.ts
export interface VramV2Provider {
  provider_id: number;
  name: string;
  connected?: boolean;
  connection_state?: string;
  provider_type?: string;
  runtime_modes?: string[];
  transport_connected?: boolean;
  last_heartbeat?: string | null;
  devices?: DeviceInfo[];
  data: VramV2Sample[];
}

// VramV2Payload from logos-ui-old/hooks/use-stats-websocket-v2.ts
export interface VramV2Payload {
  providers?: VramV2Provider[];
  last_snapshot_id?: number;
  error?: string;
}

// TimelineInitPayload from logos-ui-old/hooks/use-stats-websocket-v2.ts
export interface TimelineInitPayload {
  range?: { start: string; end: string };
  bucketSeconds?: number;
  stats?: RequestLogStats;
  events?: Array<{
    request_id: string;
    enqueue_ts: string;
    timestamp_ms: number;
    is_cloud: boolean;
  }>;
  cursor?: { enqueue_ts?: string; request_id?: string };
  error?: string;
}

// TimelineDeltaPayload from logos-ui-old/hooks/use-stats-websocket-v2.ts
export interface TimelineDeltaPayload {
  events?: Array<{
    request_id: string;
    enqueue_ts: string;
    timestamp_ms: number;
    is_cloud: boolean;
  }>;
  cursor?: { enqueue_ts?: string; request_id?: string };
  bucketSeconds?: number;
  range?: { start: string; end: string };
}

// TimelineRequestConfig from logos-ui-old/hooks/use-stats-websocket-v2.ts
export interface TimelineRequestConfig {
  start: string;
  end: string;
  targetBuckets: number;
}

// VramSeriesPoint from logos-ui-old/app/statistics.tsx lines 68-108
export type VramSeriesPoint = {
  value: number;
  label: string;
  timestamp: number;
  used_vram_gb?: number;
  remaining_vram_gb?: number;
  total_vram_gb?: number;
  models_loaded?: number;
  loaded_model_names?: string[];
  loaded_models?: Array<{ name: string; size_gb: number }>;
  _empty?: boolean;
};

// TimelineEnqueueEvent from logos-ui-old/app/statistics.tsx lines 68-108
export type TimelineEnqueueEvent = {
  request_id: string;
  enqueue_ts: string;
  timestamp_ms: number;
  is_cloud: boolean;
};

// VramProviderMeta from logos-ui-old/app/statistics.tsx lines 68-108
export type VramProviderMeta = {
  provider_id?: number;
  connected?: boolean;
  connection_state?: string;
  provider_type?: string;
  runtime_modes?: string[];
  transport_connected?: boolean;
  last_heartbeat?: string | null;
};

// VramProviderPayload from logos-ui-old/app/statistics.tsx lines 68-108
export type VramProviderPayload = {
  provider_id: number;
  name: string;
  data: Array<any>;
  connected?: boolean;
  connection_state?: string;
  provider_type?: string;
  runtime_modes?: string[];
  transport_connected?: boolean;
  last_heartbeat?: string | null;
};

// RequestItem from logos-ui-old/components/statistics/request-stack.tsx
export interface RequestItem {
  request_id: string;
  model_name: string;
  provider_name: string;
  status: string; // 'success', 'error', 'timeout', 'pending'
  timestamp: string | null;
  duration: number | null; // seconds (exec only)
  cold_start: boolean | null;
  enqueue_ts: string | null;
  scheduled_ts: string | null;
  request_complete_ts: string | null;
  queue_seconds: number | null;
  total_seconds: number | null; // enqueue to complete
  initial_priority: string | null;
  priority_when_scheduled: string | null;
  queue_depth_at_enqueue: number | null;
  error_message: string | null;
}
