package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

public record AddModelRequestDTO(
    String name,
    Integer worseLatencyId,
    Integer worseAccuracyId,
    Integer worseCostId,
    Integer worseQualityId,
    String tags,
    String description,
    Integer replicas
) {}
