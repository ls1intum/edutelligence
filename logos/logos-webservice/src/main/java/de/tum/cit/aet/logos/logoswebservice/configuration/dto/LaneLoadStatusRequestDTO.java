package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * The field is pinned to the wire name it is sent with: the webservice mixes
 * a plain ObjectMapper bean (which would not bind "provider_id" to a
 * camelCase component) with snake_case request payloads, and the other lane
 * DTOs only work because the deployed runtime applies the snake_case naming
 * strategy. Explicit is safe in both worlds.
 */
public record LaneLoadStatusRequestDTO(
        @JsonProperty("provider_id") Integer providerId,
        String model
) {}
