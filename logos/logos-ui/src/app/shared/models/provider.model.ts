export type ProviderType = 'logosnode' | 'cloud';
export type CloudProviderType = 'azure' | 'openai' | 'anthropic' | 'gemini' | 'bedrock' | 'deepseek' | 'groq' | 'none';
export type PrivacyLevel = 'LOCAL' | 'CLOUD_IN_EU_BY_US_PROVIDER' | 'CLOUD_NOT_IN_EU_BY_US_PROVIDER' | 'CLOUD_IN_EU_BY_EU_PROVIDER';

export interface Provider {
  id: number;
  name: string;
  base_url: string;
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

export interface AddProviderPayload {
  name: string;
  base_url: string;
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
  api_key?: string;
  auth_name?: string;
  auth_format?: string;
  provider_type?: ProviderType;
  cloud_provider_type?: CloudProviderType | null;
  privacy_level?: PrivacyLevel;
}
