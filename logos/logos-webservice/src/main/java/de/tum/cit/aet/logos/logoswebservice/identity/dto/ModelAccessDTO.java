package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

public record ModelAccessDTO(
    String model_name,
    @JsonInclude(JsonInclude.Include.NON_NULL)
    String provider_name,
    String provider_type,
    // Served context window in tokens, from the orchestrator's live worker
    // snapshots; null when no worker currently reports one for the model.
    //
    // Three views of the same thing, because a model can be placed with very
    // different windows on different nodes: context_window is the smallest
    // currently served (safe whichever worker answers), context_window_best
    // the largest currently served, context_window_native what the model
    // offers when a lane gets all the KV cache it wants. The last one is known
    // even when nothing is loaded, which is what a client wants when it has to
    // commit to one number up front.
    Integer context_window,
    @JsonInclude(JsonInclude.Include.NON_NULL)
    Integer context_window_best,
    @JsonInclude(JsonInclude.Include.NON_NULL)
    Integer context_window_native
) {}
