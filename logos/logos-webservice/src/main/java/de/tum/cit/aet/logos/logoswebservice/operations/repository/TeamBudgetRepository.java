package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.operations.entity.LogEntry;

public interface TeamBudgetRepository extends JpaRepository<LogEntry, Integer> {

    @Transactional(readOnly = true)
    @Query(value = """
        SELECT COALESCE(SUM(bu.cost_micro_cents), 0) AS budgetUsed
        FROM budget_usage bu
        JOIN api_keys ak ON ak.id = bu.api_key_id
        WHERE ak.team_id = :teamId AND bu.month = DATE_TRUNC('month', CURRENT_DATE)::date
        """, nativeQuery = true)
    TeamBudgetProjection findBudgetUsedByTeam(@Param("teamId") int teamId);
}
