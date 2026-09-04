package de.tum.cit.aet.logos.logoswebservice.operations.dto;

public record RunModelBenchmarkRequestDTO(
    Integer modelProviderId,
    Integer sampleSize,
    Integer maxOutputTokens
) {}
