package de.tum.cit.aet.logos.logoswebservice.identity.dto;

public record UpdateTeamRequestDTO(
    Integer default_cloud_rpm_limit,
    Integer default_cloud_tpm_limit,
    Integer default_local_rpm_limit,
    Integer default_local_tpm_limit,
    Long default_monthly_budget_micro_cents,
    Long team_monthly_budget_micro_cents
) {}
