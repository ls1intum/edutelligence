package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record UpdateModelRequest(
    @JsonProperty("model_id") Integer modelId,
    String name,
    String description,
    String tags,
    Integer parallel,
    @JsonProperty("weight_latency") Integer weightLatency,
    @JsonProperty("weight_accuracy") Integer weightAccuracy,
    @JsonProperty("weight_cost") Integer weightCost,
    @JsonProperty("weight_quality") Integer weightQuality
) {}
