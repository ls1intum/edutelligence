package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

public record ModelCapabilitiesDTO(
    Integer modelId,
    boolean supportsFunctionCalling,
    boolean supportsVision,
    boolean supportsReasoning
) {}
