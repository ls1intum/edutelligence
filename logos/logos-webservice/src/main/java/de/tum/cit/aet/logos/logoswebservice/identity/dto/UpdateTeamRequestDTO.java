package de.tum.cit.aet.logos.logoswebservice.identity.dto;

public record UpdateTeamRequestDTO(
    Integer default_cloud_rpm_limit,
    Integer default_cloud_tpm_limit,
    Integer default_local_rpm_limit,
    Integer default_local_tpm_limit,
    Long default_monthly_budget_micro_cents,
    Long team_monthly_budget_micro_cents,
    /** When non-null, publishes or hides the team on the public stats page. */
    Boolean show_on_public_stats,
    /** When non-null, sets the public stats category; blank clears it. */
    String public_category
) {}
