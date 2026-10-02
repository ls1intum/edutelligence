package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import jakarta.persistence.LockModeType;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiLlmCallRecommendation;

public interface AiLlmCallRecommendationRepository extends JpaRepository<AiLlmCallRecommendation, Integer> {
    List<AiLlmCallRecommendation> findByAnalysisIdOrderByIdAsc(Integer analysisId);

    List<AiLlmCallRecommendation> findByTeamIdAndReviewStatusOrderByIdAsc(Integer teamId, String reviewStatus);

    Optional<AiLlmCallRecommendation> findByIdAndTeamId(Integer id, Integer teamId);

    /**
     * Same row, locked for the rest of the transaction. Every write path takes
     * it: rows are saved whole, so two writers that read the same version
     * would otherwise overwrite each other's fields (a model pick undoing a
     * review, or the other way round).
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT r FROM AiLlmCallRecommendation r WHERE r.id = :id AND r.teamId = :teamId")
    Optional<AiLlmCallRecommendation> lockByIdAndTeamId(@Param("id") Integer id, @Param("teamId") Integer teamId);
}
