package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

import java.util.Map;

public record AddLaneRequestDTO(
        Integer providerId,
        Map<String, Object> lane
) {}
