package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

public record ReleaseCalibrationClaimRequestDTO(
    Integer providerId,
    String claimToken
) {}
