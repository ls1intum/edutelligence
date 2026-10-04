package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

public record ModelAccessDTO(
    String model_name,
    @JsonInclude(JsonInclude.Include.NON_NULL)
    String provider_name,
    String provider_type,
    // Context window in tokens, from the orchestrator's live worker snapshots;
    // null when nothing is known for the model.
    //
    // Three views of the same thing, because a model can be served with very
    // different windows at once: context_window_current_min is the smallest
    // being served right now (holds whichever deployment answers),
    // context_window_current_max the largest, and context_window_overall the
    // widest this model is ever served with. The last one is known even when
    // nothing is loaded, which is what a client needs when it has to commit to
    // one number up front.
    Integer context_window_current_min,
    @JsonInclude(JsonInclude.Include.NON_NULL)
    Integer context_window_current_max,
    @JsonInclude(JsonInclude.Include.NON_NULL)
    Integer context_window_overall
) {}
