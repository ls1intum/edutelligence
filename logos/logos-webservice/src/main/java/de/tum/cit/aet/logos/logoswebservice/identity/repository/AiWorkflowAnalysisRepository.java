package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiWorkflowAnalysis;

public interface AiWorkflowAnalysisRepository extends JpaRepository<AiWorkflowAnalysis, Integer> {
    List<AiWorkflowAnalysis> findByTeamIdOrderByStartedAtDesc(Integer teamId);

    Optional<AiWorkflowAnalysis> findFirstByTeamRepositoryIdAndStatusOrderByFinishedAtDesc(
        Integer teamRepositoryId, String status);

    Optional<AiWorkflowAnalysis> findByIdAndTeamId(Integer id, Integer teamId);
}
