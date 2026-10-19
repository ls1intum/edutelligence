package de.tum.cit.aet.logos.logoswebservice.operations.repository;

/**
 * Delay percentiles of finished cloud requests for one model on one provider.
 * Every figure is in milliseconds; a percentile is null when no row in the
 * group carries the stamps it needs.
 */
public interface CloudLatencyProjection {
    Integer getModelId();
    String getModelName();
    Integer getProviderId();
    String getProviderName();
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
