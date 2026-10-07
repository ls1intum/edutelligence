package de.tum.cit.aet.logos.logoswebservice.identity.dto;

public record ReviewRecommendationRequestDTO(
    String action,
    String confirmedSlo,
    java.util.List<String> confirmedObjectivePriority,
    Integer apiKeyId,
    // True when the owner chose "No key": the review binds and re-prioritises
    // no key, not even the one the recommendation was linked to before.
    Boolean noApiKey
) {}
