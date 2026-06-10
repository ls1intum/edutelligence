package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

public record ConnectModelProviderRequestDTO(
    Integer providerId,
    Integer modelId,
    String endpoint,
    String apiKey
) {}
