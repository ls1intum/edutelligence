package de.tum.cit.aet.logos.logoswebservice.identity.dto;

public record ModelAccessDTO(
    String model_name,
    String provider_name,
    String provider_type
) {}
