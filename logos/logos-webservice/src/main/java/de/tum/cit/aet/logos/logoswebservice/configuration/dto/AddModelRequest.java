package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record AddModelRequest(
    String name,
    @JsonProperty("worse_latency") Integer worseLatencyId,
    @JsonProperty("worse_accuracy") Integer worseAccuracyId,
    @JsonProperty("worse_cost") Integer worseCostId,
    @JsonProperty("worse_quality") Integer worseQualityId,
    String tags,
    Integer parallel,
    String description
) {}
