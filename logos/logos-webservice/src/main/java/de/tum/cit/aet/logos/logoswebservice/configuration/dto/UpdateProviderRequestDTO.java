package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

public record UpdateProviderRequestDTO(
    Integer providerId,
    String providerName,
    String baseUrl,
    String apiKey,
    String authName,
    String authFormat,
    String providerType,
    String cloudProviderType,
    String privacyLevel
) {}
