package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

public record ModelAccessDTO(
    String model_name,
    @JsonInclude(JsonInclude.Include.NON_NULL)
    String provider_name,
    String provider_type,
    // Served context window in tokens, from the orchestrator's live worker
    // snapshots; null when no worker currently reports one for the model.
    Integer context_window
) {}
