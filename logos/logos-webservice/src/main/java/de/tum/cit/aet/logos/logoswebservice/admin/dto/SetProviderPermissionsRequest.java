package de.tum.cit.aet.logos.logoswebservice.admin.dto;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

public record SetProviderPermissionsRequest(
    @JsonProperty("provider_ids") List<Integer> providerIds
) {}