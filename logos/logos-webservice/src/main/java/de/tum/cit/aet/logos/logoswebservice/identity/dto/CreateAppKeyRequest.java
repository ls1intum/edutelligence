package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record CreateAppKeyRequest(
    String name,
    @JsonProperty("key_type") String keyType,
    String environment,
    String log,
    Object settings,
    @JsonProperty("default_priority") Integer defaultPriority,
    @JsonProperty("use_custom_permissions") Boolean useCustomPermissions
) {}
