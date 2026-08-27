export type ProviderType = 'logosnode' | 'cloud';
export type CloudProviderType = 'azure' | 'openai' | 'anthropic' | 'gemini' | 'bedrock' | 'deepseek' | 'groq' | 'none';
export type PrivacyLevel = 'LOCAL' | 'CLOUD_IN_EU_BY_US_PROVIDER' | 'CLOUD_NOT_IN_EU_BY_US_PROVIDER' | 'CLOUD_IN_EU_BY_EU_PROVIDER';

export interface Provider {
  id: number;
  name: string;
  base_url: string | null;
  api_key: string | null;
  auth_name: string | null;
  auth_format: string | null;
  provider_type: ProviderType;
  cloud_provider_type: CloudProviderType | null;
  privacy_level: PrivacyLevel;
}

export interface ModelConnection {
  model_id: number;
  model_name: string;
  endpoint: string | null;
  api_key: string | null;
}

export interface PerformancePercentiles {
  p50: number | null;
  p95: number | null;
  p100: number | null;
}

export interface ProviderPerformancePair {
  provider_id: number;
  provider_name: string;
  model_id: number;
  model_name: string;
  request_count: number;
  successful_request_count: number;
  success_rate: number;
  cold_start_count: number;
  cold_start_rate: number;
  ttft_ms: PerformancePercentiles;
  tpot_ms: PerformancePercentiles;
  ttlt_ms: PerformancePercentiles;
}

export interface ProviderPerformanceResponse {
  from: string;
  to: string;
  pairs: ProviderPerformancePair[];
}

export interface GuideLlmPercentiles {
  p50: number;
  p95: number;
  p99: number;
}

export interface GuideLlmDistributionSummary {
  mean?: number;
  max?: number;
  percentiles: GuideLlmPercentiles;
}

export interface GuideLlmStatusDistributionSummary {
  successful: GuideLlmDistributionSummary;
}

export interface GuideLlmMetrics {
  request_totals: {
    successful: number;
    incomplete: number;
    errored: number;
    total: number;
  };
  request_latency?: GuideLlmStatusDistributionSummary;
  time_to_first_token_ms?: GuideLlmStatusDistributionSummary;
  time_per_output_token_ms?: GuideLlmStatusDistributionSummary;
  output_tokens_per_second?: GuideLlmStatusDistributionSummary;
}

export interface ModelProviderBenchmark {
  id: number;
  model_provider_id: number;
  provider_id: number;
  provider_name: string;
  model_id: number;
  model_name: string;
  configuration: Record<string, unknown>;
  dataset: string;
  sample_size: number;
  metrics: GuideLlmMetrics;
  recorded_at: string;
}

export interface ModelBenchmarkPair {
  model_provider_id: number;
  provider_id: number;
  provider_name: string;
  provider_type: ProviderType;
  model_id: number;
  model_name: string;
  endpoint_configured: boolean;
  authentication_configured: boolean;
}

export type ModelBenchmarkRunStatus = 'pending' | 'running' | 'success' | 'failed';

export interface ModelBenchmarkRun {
  id: number;
  status: ModelBenchmarkRunStatus;
  request: {
    model_provider_id: number;
    provider_id: number;
    provider_name: string;
    model_id: number;
    model_name: string;
    dataset: string;
    subset: string;
    split: string;
    samples: number;
    max_output_tokens: number;
  };
  result: {
    stage?: string;
    benchmark_id?: number;
  };
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface StartModelBenchmarkResponse {
  job_id: number;
  status: ModelBenchmarkRunStatus;
  provider_id: number;
  provider_name: string;
  model_provider_id: number;
  model_name: string;
}

export interface ModelBenchmarkResponse {
  benchmarks: ModelProviderBenchmark[];
  pairs: ModelBenchmarkPair[];
  runs: ModelBenchmarkRun[];
}

export interface AddProviderPayload {
  name: string;
  base_url?: string;
  api_key?: string;
  auth_name?: string;
  auth_format?: string;
  provider_type: ProviderType;
  cloud_provider_type?: CloudProviderType;
  privacy_level: PrivacyLevel;
}

export interface UpdateProviderPayload {
  provider_id: number;
  name?: string;
  base_url?: string;
  api_key: string;
  auth_name: string;
  auth_format: string;
  provider_type?: ProviderType;
  cloud_provider_type?: CloudProviderType | null;
  privacy_level?: PrivacyLevel;
}
