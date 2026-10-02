package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.AiLlmCallRecommendation;

public interface AiLlmCallRecommendationRepository extends JpaRepository<AiLlmCallRecommendation, Integer> {
    List<AiLlmCallRecommendation> findByAnalysisIdOrderByIdAsc(Integer analysisId);

    List<AiLlmCallRecommendation> findByTeamIdAndReviewStatusOrderByIdAsc(Integer teamId, String reviewStatus);

    Optional<AiLlmCallRecommendation> findByIdAndTeamId(Integer id, Integer teamId);
}
