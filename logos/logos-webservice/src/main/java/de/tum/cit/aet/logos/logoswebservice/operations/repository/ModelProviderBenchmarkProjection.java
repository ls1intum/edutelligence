package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.time.Instant;

public interface ModelProviderBenchmarkProjection {
    Integer getId();
    Integer getModelProviderId();
    Integer getProviderId();
    String getProviderName();
    Integer getModelId();
    String getModelName();
    String getConfigurationJson();
    String getDataset();
    Integer getSampleSize();
    String getMetricsJson();
    Instant getRecordedAt();
}
