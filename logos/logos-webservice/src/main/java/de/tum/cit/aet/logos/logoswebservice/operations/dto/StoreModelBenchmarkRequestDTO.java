package de.tum.cit.aet.logos.logoswebservice.operations.dto;

import java.time.Instant;
import java.util.Map;

public record StoreModelBenchmarkRequestDTO(
    Integer modelProviderId,
    Map<String, Object> configuration,
    String dataset,
    Integer sampleSize,
    Map<String, Object> metrics,
    Instant recordedAt
) {}
