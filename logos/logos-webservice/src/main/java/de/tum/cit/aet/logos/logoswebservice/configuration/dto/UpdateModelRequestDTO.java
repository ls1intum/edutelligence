package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

import java.util.Map;

public record UpdateModelRequestDTO(
    Integer modelId,
    String name,
    String description,
    String tags,
    Integer weightLatency,
    Integer weightAccuracy,
    Integer weightCost,
    Integer weightQuality,
    /**
     * Optional explicit replacement of the weight-override set (issue #651):
     * which dimensions the metrics derivation must not touch. When omitted,
     * weight values that actually change are auto-marked as overrides.
     */
    Map<String, Boolean> weightOverrides
) {
    public UpdateModelRequestDTO(Integer modelId, String name, String description, String tags,
                                 Integer weightLatency, Integer weightAccuracy,
                                 Integer weightCost, Integer weightQuality) {
        this(modelId, name, description, tags, weightLatency, weightAccuracy, weightCost, weightQuality, null);
    }
}
