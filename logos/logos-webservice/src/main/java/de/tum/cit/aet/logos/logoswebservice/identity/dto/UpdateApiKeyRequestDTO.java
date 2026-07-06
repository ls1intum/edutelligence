package de.tum.cit.aet.logos.logoswebservice.identity.dto;

public record UpdateApiKeyRequestDTO(
    String environment,
    Integer defaultPriority,
    String log,
    Long budgetLimitMicroCents,
    Integer cloudRpmLimit,
    Integer cloudTpmLimit,
    Integer localRpmLimit,
    Integer localTpmLimit,
    Boolean useCustomPermissions
) {}
