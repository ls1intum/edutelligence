package de.tum.cit.aet.logos.logoswebservice.operations.dto;

public record RunModelBenchmarkRequestDTO(
    Integer modelProviderId,
    Integer sampleSize,
    Integer maxOutputTokens,
    String dataset,
    String subset,
    String split,
    String textColumn,
    String profile,
    Integer concurrency,
    Integer seed,
    java.util.Map<String, Object> servingOverrides
) {}
