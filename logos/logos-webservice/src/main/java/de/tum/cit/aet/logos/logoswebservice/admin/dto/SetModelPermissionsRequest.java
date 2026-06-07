package de.tum.cit.aet.logos.logoswebservice.admin.dto;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

public record SetModelPermissionsRequest(
    @JsonProperty("model_ids") List<Integer> modelIds
) {}