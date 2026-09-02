export interface Model {
  id: number;
  name: string;
  description: string | null;
  tags: string | null;
  /** Comma-joined alternative names the model can be requested by. */
  aliases: string | null;
  weight_latency: number | null;
  weight_accuracy: number | null;
  weight_cost: number | null;
  weight_quality: number | null;
  /** Only present for logos_admin (the endpoint is open to all roles). */
  last_used_at?: string | null;
}

export interface AddModelPayload {
  name: string;
  description?: string;
  tags?: string;
  aliases?: string[];
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
  /** Full replacement list; an empty list removes all aliases. */
  aliases?: string[];
  weight_latency?: number;
  weight_accuracy?: number;
  weight_cost?: number;
  weight_quality?: number;
}
