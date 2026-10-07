package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiWorkflowAnalysis;

public interface AiWorkflowAnalysisRepository extends JpaRepository<AiWorkflowAnalysis, Integer> {
    List<AiWorkflowAnalysis> findByTeamIdOrderByStartedAtDesc(Integer teamId);

    /**
     * The repository's latest succeeded analysis. One ordering everywhere —
     * the Workflows tab, the superseded-edit check and the agent ingest all
     * sort NULL finish times last and break ties by id — so they agree on
     * which analysis is current.
     */
    @Query(value = """
        SELECT * FROM ai_workflow_analyses
         WHERE team_repository_id = :repoId AND status = 'succeeded'
         ORDER BY finished_at DESC NULLS LAST, id DESC
         LIMIT 1
        """, nativeQuery = true)
    Optional<AiWorkflowAnalysis> findLatestSucceeded(@Param("repoId") Integer teamRepositoryId);

    Optional<AiWorkflowAnalysis> findByIdAndTeamId(Integer id, Integer teamId);

    void deleteByTeamRepositoryId(Integer teamRepositoryId);
}
