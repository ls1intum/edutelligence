package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

public record AddProviderRequestDTO(
    String providerName,
    String baseUrl,
    String apiKey,
    String authName,
    String authFormat,
    String providerType,
    String cloudProviderType,
    String privacyLevel
) {}
