export interface Model {
  id: number;
  name: string;
  description: string | null;
  tags: string | null;
  parallel: number | null;
  weight_latency: number | null;
  weight_accuracy: number | null;
  weight_cost: number | null;
  weight_quality: number | null;
}

export interface AddModelPayload {
  name: string;
  description?: string;
  tags?: string;
  parallel?: number;
  worse_latency_id?: number;
  worse_accuracy_id?: number;
  worse_cost_id?: number;
  worse_quality_id?: number;
}

export interface UpdateModelPayload {
  model_id: number;
  name?: string;
  description?: string;
  tags?: string;
  parallel?: number;
  weight_latency?: number;
  weight_accuracy?: number;
  weight_cost?: number;
  weight_quality?: number;
}
