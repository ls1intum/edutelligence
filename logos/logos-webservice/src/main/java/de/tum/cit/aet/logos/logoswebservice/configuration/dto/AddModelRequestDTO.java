package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

import java.util.List;

public record AddModelRequestDTO(
    String name,
    Integer worseLatencyId,
    Integer worseAccuracyId,
    Integer worseCostId,
    Integer worseQualityId,
    String tags,
    String description,
    List<String> aliases
) {}
