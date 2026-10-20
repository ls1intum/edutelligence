package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

public record LockLaneRequestDTO(
        Integer providerId,
        String laneId,
        String modelName
) {}
