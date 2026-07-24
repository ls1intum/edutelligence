package de.tum.cit.aet.logos.logoswebservice.identity.dto;

public record ModelAccessDTO(
    String model_name,
    String provider_name,
    String provider_type,
    // Served context window in tokens, from the orchestrator's live worker
    // snapshots; null when no worker currently reports one for the model.
    Integer context_window
) {}
