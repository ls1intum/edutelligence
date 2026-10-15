package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamProviderBudget;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamProviderBudgetId;

public interface TeamProviderBudgetRepository
        extends JpaRepository<TeamProviderBudget, TeamProviderBudgetId> {

    List<TeamProviderBudget> findById_TeamId(Integer teamId);

    @Query(value = """
        SELECT tpb.provider_id AS provider_id,
               p.name AS provider_name,
               p.provider_type AS provider_type,
               tpb.monthly_budget_micro_cents AS monthly_budget_micro_cents
        FROM team_provider_budgets tpb
        JOIN providers p ON p.id = tpb.provider_id
        WHERE tpb.team_id = :teamId
        ORDER BY p.name
        """, nativeQuery = true)
    List<TeamProviderBudgetProjection> listForTeam(@Param("teamId") Integer teamId);

    interface TeamProviderBudgetProjection {
        Integer getProviderId();
        String getProviderName();
        String getProviderType();
        Long getMonthlyBudgetMicroCents();
    }
}
