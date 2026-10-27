package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

/**
 * A model-request vote: the model name and the team it is wanted for. The
 * team is what the next step (the team's app admin accepting a gated model's
 * license agreement) is keyed to, so it is part of the request, not an
 * annotation on top of it.
 */
public record SubmitModelRequestDTO(
    String name,
    Integer teamId
) {}
