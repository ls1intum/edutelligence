package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

/**
 * A requested model as the Models page reports it: the registry row id, the
 * model name, how many users have voted for it, whether the calling user has,
 * whether the Hugging Face repository is gated for the central HF_TOKEN
 * (null until the precheck has produced a verdict), and the team that first
 * requested the model (null until a vote named one). With the global
 * SNAKE_CASE naming strategy this serializes to {@code id}/{@code name}/
 * {@code request_count}/{@code has_voted}/{@code is_gated}/
 * {@code first_requesting_team}.
 */
public record RequestedModelResponse(
    Integer id,
    String name,
    Integer requestCount,
    Boolean hasVoted,
    Boolean isGated,
    Integer firstRequestingTeam
) {}
