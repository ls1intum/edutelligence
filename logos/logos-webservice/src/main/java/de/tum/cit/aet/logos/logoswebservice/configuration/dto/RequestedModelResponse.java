package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

/**
 * A requested model as the Models page reports it: the registry row id, the
 * model name, how many users have voted for it, and whether the calling user
 * has. With the global SNAKE_CASE naming strategy this serializes to
 * {@code id}/{@code name}/{@code request_count}/{@code has_voted}.
 */
public record RequestedModelResponse(
    Integer id,
    String name,
    Integer requestCount,
    Boolean hasVoted
) {}
