/**
 * Delay percentiles of finished cloud requests for one model on one provider,
 * as `POST /api/logosdb/cloud_latency_stats` returns them. All figures are in
 * milliseconds; a percentile is `null` when no request in the group carries
 * the timestamps it needs.
 */
export interface CloudLatencyRow {
  modelId: number | null;
  modelName: string;
  providerId: number | null;
  providerName: string;
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

export interface CloudLatencyStats {
  range: { start: string; end: string };
  rows: CloudLatencyRow[];
}

/** The page scope the cloud delay table is narrowed to; `null` means "do not narrow by it". */
export interface CloudLatencyScope {
  teamId: number | null;
  userId: number | null;
  providerId: number | null;
  apiKeyId: number | null;
  modelIds: number[];
}
