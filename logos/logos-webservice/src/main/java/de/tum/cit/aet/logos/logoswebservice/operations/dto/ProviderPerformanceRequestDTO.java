package de.tum.cit.aet.logos.logoswebservice.operations.dto;

import java.time.Instant;

public record ProviderPerformanceRequestDTO(
    Integer providerId,
    Integer modelId,
    Instant from,
    Instant to
) {}
