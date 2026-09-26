package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

public record SetModelCapabilitiesRequestDTO(
    Integer modelId,
    Boolean supportsFunctionCalling,
    Boolean supportsVision,
    Boolean supportsReasoning
) {}
