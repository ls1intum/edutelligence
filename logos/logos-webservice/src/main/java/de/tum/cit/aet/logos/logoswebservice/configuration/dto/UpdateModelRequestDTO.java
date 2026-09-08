package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

import java.util.List;

public record UpdateModelRequestDTO(
    Integer modelId,
    String name,
    String description,
    String tags,
    Integer weightLatency,
    Integer weightAccuracy,
    Integer weightCost,
    Integer weightQuality,
    List<String> aliases
) {}
