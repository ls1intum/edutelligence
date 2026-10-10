package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.Collection;
import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiWorkflowStep;

public interface AiWorkflowStepRepository extends JpaRepository<AiWorkflowStep, Integer> {
    List<AiWorkflowStep> findByWorkflowIdOrderBySortOrderAsc(Integer workflowId);

    List<AiWorkflowStep> findByWorkflowIdInOrderByWorkflowIdAscSortOrderAsc(Collection<Integer> workflowIds);
}
