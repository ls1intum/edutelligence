package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiWorkflow;

public interface AiWorkflowRepository extends JpaRepository<AiWorkflow, Integer> {
    List<AiWorkflow> findByAnalysisIdOrderBySortOrderAsc(Integer analysisId);
}
