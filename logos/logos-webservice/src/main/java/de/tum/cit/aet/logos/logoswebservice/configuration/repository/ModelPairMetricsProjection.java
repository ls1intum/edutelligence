package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.math.BigDecimal;
import java.time.Instant;

public interface ModelPairMetricsProjection {
    Integer getModelId();
    String getModelName();
    Integer getProviderId();
    String getProviderName();
    String getProviderType();
    String getCloudProviderType();
    Integer getDerivedTtftMs();
    Integer getDerivedTotalLatencyMs();
    Integer getDerivedTpotMs();
    BigDecimal getDerivedCostUsd();
    Integer getDerivedSamples();
    Instant getDerivedUpdatedAt();
}
