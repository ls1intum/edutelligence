package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record UpdateProviderRequest(
    @JsonProperty("provider_id") Integer providerId,
    @JsonProperty("provider_name") String providerName,
    @JsonProperty("base_url") String baseUrl,
    @JsonProperty("api_key") String apiKey,
    @JsonProperty("auth_name") String authName,
    @JsonProperty("auth_format") String authFormat,
    @JsonProperty("provider_type") String providerType,
    @JsonProperty("cloud_provider_type") String cloudProviderType,
    @JsonProperty("privacy_level") String privacyLevel
) {}
