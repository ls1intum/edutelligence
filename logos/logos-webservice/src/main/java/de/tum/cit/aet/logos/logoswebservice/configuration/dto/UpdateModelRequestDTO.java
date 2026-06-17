package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

public record UpdateModelRequestDTO(
    Integer modelId,
    String name,
    String description,
    String tags,
    Integer parallel,
    Integer weightLatency,
    Integer weightAccuracy,
    Integer weightCost,
    Integer weightQuality
) {}
