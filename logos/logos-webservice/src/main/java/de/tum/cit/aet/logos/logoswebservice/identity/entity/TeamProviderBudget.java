package de.tum.cit.aet.logos.logoswebservice.identity.entity;

import jakarta.persistence.Column;
import jakarta.persistence.EmbeddedId;
import jakarta.persistence.Entity;
import jakarta.persistence.Table;

@Entity
@Table(name = "team_provider_budgets")
public class TeamProviderBudget {

    @EmbeddedId
    private TeamProviderBudgetId id;

    /** Null means unlimited for this provider (sponsored). */
    @Column(name = "monthly_budget_micro_cents")
    private Long monthlyBudgetMicroCents;

    public TeamProviderBudget() {}

    public TeamProviderBudget(Integer teamId, Integer providerId, Long monthlyBudgetMicroCents) {
        this.id = new TeamProviderBudgetId(teamId, providerId);
        this.monthlyBudgetMicroCents = monthlyBudgetMicroCents;
    }

    public TeamProviderBudgetId getId() { return id; }
    public void setId(TeamProviderBudgetId id) { this.id = id; }

    public Long getMonthlyBudgetMicroCents() { return monthlyBudgetMicroCents; }
    public void setMonthlyBudgetMicroCents(Long monthlyBudgetMicroCents) {
        this.monthlyBudgetMicroCents = monthlyBudgetMicroCents;
    }
}
