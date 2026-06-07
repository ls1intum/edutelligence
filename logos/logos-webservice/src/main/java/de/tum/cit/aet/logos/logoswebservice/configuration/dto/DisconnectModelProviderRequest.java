package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record DisconnectModelProviderRequest(
    @JsonProperty("model_id") Integer modelId,
    @JsonProperty("provider_id") Integer providerId
) {}
