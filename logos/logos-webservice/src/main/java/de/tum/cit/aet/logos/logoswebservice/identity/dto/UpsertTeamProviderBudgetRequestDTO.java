package de.tum.cit.aet.logos.logoswebservice.identity.dto;

/**
 * Create or replace a per-provider monthly budget for a team.
 *
 * <p>{@code monthly_budget_micro_cents} null means unlimited (sponsored) for
 * that provider; any other value (0 included) is a dedicated cap that does not
 * draw from the team's default monthly member budget.
 */
public record UpsertTeamProviderBudgetRequestDTO(
    Integer provider_id,
    Long monthly_budget_micro_cents
) {}
