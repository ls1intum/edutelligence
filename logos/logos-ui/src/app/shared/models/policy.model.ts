export type ThresholdLevel =
  | 'LOCAL'
  | 'CLOUD_IN_EU_BY_EU_PROVIDER'
  | 'CLOUD_IN_EU_BY_US_PROVIDER'
  | 'CLOUD_NOT_IN_EU_BY_US_PROVIDER';

// API returns snake_case (backend uses manual toMap() with snake_case keys)
export interface Policy {
  id: number;
  name: string;
  description: string | null;
  threshold_privacy: string;
  threshold_latency: number;
  threshold_accuracy: number;
  threshold_cost: number;
  threshold_quality: number;
  priority: number;
  topic: string | null;
  api_key_id: number | null;
  team_id: number | null;
}

// API expects snake_case (spring.jackson.property-naming-strategy=SNAKE_CASE)
export interface AddPolicyPayload {
  name: string;
  description: string;
  threshold_privacy: string;
  threshold_latency: number;
  threshold_accuracy: number;
  threshold_cost: number;
  threshold_quality: number;
  priority: number;
  topic: string | null;
  api_key_id: number | null;
  team_id: number | null;
}

export interface UpdatePolicyPayload extends AddPolicyPayload {
  id: number;
}
