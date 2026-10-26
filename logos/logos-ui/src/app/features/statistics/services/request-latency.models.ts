/**
 * Delay percentiles of finished requests for one model on one provider at one
 * reasoning effort, as `POST /api/logosdb/request_latency_stats` returns them.
 * Covers local and cloud providers. All figures are in milliseconds; a
 * percentile is `null` when no request in the group carries the timestamps it
 * needs.
 */
export interface RequestLatencyRow {
  modelId: number | null;
  modelName: string;
  providerId: number | null;
  providerName: string;
  /** Whether the provider is a local worker rather than a cloud provider. */
  local: boolean;
  /**
   * The reasoning effort sent to the provider, after Logos mapped it onto the
   * levels the model supports. `null` when the request carried none.
   */
  reasoningEffort: string | null;
  requestCount: number;
  errorCount: number;
  /** Time inside Logos before the provider call: key lookup, rate limit, budget check, connection wait. */
  queueP50Ms: number | null;
  queueP95Ms: number | null;
  /** The provider's own time, from the call to the end of its response. */
  upstreamP50Ms: number | null;
  upstreamP95Ms: number | null;
  /** How many requests reported a first token. */
  ttftSamples: number;
  /** Time to first token, from arrival. */
  ttftP50Ms: number | null;
  ttftP95Ms: number | null;
}

export interface RequestLatencyStats {
  range: { start: string; end: string };
  rows: RequestLatencyRow[];
}

/** The page scope the delay table is narrowed to; `null` means "do not narrow by it". */
export interface RequestLatencyScope {
  teamId: number | null;
  userId: number | null;
  providerId: number | null;
  apiKeyId: number | null;
  modelIds: number[];
}
