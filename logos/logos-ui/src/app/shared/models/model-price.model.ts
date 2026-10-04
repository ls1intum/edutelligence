/**
 * One catalogue price row as returned by /logosdb/get_model_prices.
 * `price_per_k_unit` is micro-cents per 1000 units of `unit`; rows are
 * ordered chronologically within each (quantity, unit, context tier,
 * service tier) dimension, so the last row is the current rate.
 */
export interface ModelPriceEntry {
  quantity: string;
  unit: string;
  min_context_tokens: number;
  service_tier: string;
  price_per_k_unit: number;
  valid_from: string;
}

export interface ModelProviderPrices {
  provider_id: number;
  provider_name: string;
  provider_type: 'logosnode' | 'cloud';
  cloud_provider_type: string | null;
  prices: readonly ModelPriceEntry[];
}

export interface ModelPriceResponse {
  model_id: number;
  providers: readonly ModelProviderPrices[];
}
