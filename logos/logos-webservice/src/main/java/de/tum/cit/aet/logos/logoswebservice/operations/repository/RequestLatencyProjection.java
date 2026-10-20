package de.tum.cit.aet.logos.logoswebservice.operations.repository;

/**
 * Delay percentiles of finished requests for one model on one provider at one
 * reasoning effort. Every figure is in milliseconds; a percentile is null when
 * no row in the group carries the stamps it needs.
 */
public interface RequestLatencyProjection {
    Integer getModelId();
    String getModelName();
    Integer getProviderId();
    String getProviderName();
    /** Whether the provider runs on local workers (or is unknown). */
    Boolean getLocal();
    /** The effort the requests were served with; null when they carried none. */
    String getReasoningEffort();
    Long getRequestCount();
    Long getErrorCount();
    Double getQueueP50Ms();
    Double getQueueP95Ms();
    Double getUpstreamP50Ms();
    Double getUpstreamP95Ms();
    Long getTtftSamples();
    Double getTtftP50Ms();
    Double getTtftP95Ms();
}
