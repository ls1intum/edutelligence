package de.tum.cit.aet.logos.logoswebservice.identity.dto;

public record ReviewRecommendationRequestDTO(
    String action,
    String confirmedSla,
    java.util.List<String> confirmedObjectivePriority,
    Integer apiKeyId
) {}
