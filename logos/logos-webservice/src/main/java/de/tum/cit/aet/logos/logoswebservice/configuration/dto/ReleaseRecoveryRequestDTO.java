package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

public record ReleaseRecoveryRequestDTO(
    Integer modelProviderId,
    Boolean force
) {}
