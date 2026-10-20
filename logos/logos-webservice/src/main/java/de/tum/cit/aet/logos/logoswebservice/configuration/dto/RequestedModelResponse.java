package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

/**
 * A requested model as the Models page reports it: the registry row id, the
 * model name, how many users have voted for it, whether the calling user has,
 * and the last decisive Hugging Face verdict (null until the precheck has
 * produced one). With the global SNAKE_CASE naming strategy this serializes
 * to {@code id}/{@code name}/{@code request_count}/{@code has_voted}/
 * {@code hugging_face_status}.
 */
public record RequestedModelResponse(
    Integer id,
    String name,
    Integer requestCount,
    Boolean hasVoted,
    String huggingFaceStatus
) {}
