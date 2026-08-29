package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

public record UpdateModelRequestDTO(
    Integer modelId,
    String name,
    String description,
    String tags,
    Integer weightLatency,
    Integer weightAccuracy,
    Integer weightCost,
    Integer weightQuality
) {}
