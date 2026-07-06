package de.tum.cit.aet.logos.logoswebservice.identity.dto;

public record CreateAppKeyRequestDTO(
    String name,
    String keyType,
    String environment,
    String log,
    Object settings,
    Integer defaultPriority,
    Boolean useCustomPermissions
) {}
