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
    java.util.Map<String, Integer> profileRatings,
    List<String> aliases,
    /**
     * Optional capability override. Null means "leave capabilities alone";
     * otherwise all three flags must be present (validated in
     * {@code ModelService.updateModelInfo}).
     */
    Boolean supportsFunctionCalling,
    Boolean supportsVision,
    Boolean supportsReasoning
) {}
