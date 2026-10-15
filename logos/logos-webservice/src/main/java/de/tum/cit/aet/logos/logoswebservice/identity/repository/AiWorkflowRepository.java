package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import jakarta.persistence.LockModeType;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiWorkflow;

public interface AiWorkflowRepository extends JpaRepository<AiWorkflow, Integer> {
    List<AiWorkflow> findByAnalysisIdOrderBySortOrderAsc(Integer analysisId);

    /**
     * Same row, locked for the rest of the transaction. Owner diagram edits
     * and proposal reviews take it so they do not race the agent ingest that
     * copies the previous analysis's owner-edited diagrams.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT w FROM AiWorkflow w WHERE w.id = :id")
    Optional<AiWorkflow> lockById(@Param("id") Integer id);
}
