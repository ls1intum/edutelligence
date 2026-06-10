package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.time.Instant;

public interface VramSnapshotProjection {
    Integer getId();
    Integer getProviderId();
    String getProviderName();
    Instant getSnapshotTs();
    Long getTotalVramUsedBytes();
    Long getTotalMemoryBytes();
    Long getFreeMemoryBytes();
    Integer getTotalModelsLoaded();
    String getLoadedModels();
    String getSchedulerSignals();
    Integer getTotalVramMb();
    Long getCapacityBytes();
}
