package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record UpdateApiKeyRequest(
    String environment,
    @JsonProperty("default_priority") Integer defaultPriority,
    String log,
    @JsonProperty("budget_limit_micro_cents") Long budgetLimitMicroCents,
    @JsonProperty("cloud_rpm_limit") Integer cloudRpmLimit,
    @JsonProperty("cloud_tpm_limit") Integer cloudTpmLimit,
    @JsonProperty("local_rpm_limit") Integer localRpmLimit,
    @JsonProperty("local_tpm_limit") Integer localTpmLimit,
    @JsonProperty("use_custom_permissions") Boolean useCustomPermissions
) {}
