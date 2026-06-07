package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record ConnectModelProviderRequest(
    @JsonProperty("provider_id") Integer providerId,
    @JsonProperty("model_id") Integer modelId,
    String endpoint,
    @JsonProperty("api_key") String apiKey
) {}
