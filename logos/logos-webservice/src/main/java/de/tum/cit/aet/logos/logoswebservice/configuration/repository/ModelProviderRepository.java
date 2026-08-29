package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelProvider;

public interface ModelProviderRepository extends JpaRepository<ModelProvider, Integer> {
    Optional<ModelProvider> findByModelIdAndProviderId(Integer modelId, Integer providerId);
    void deleteByModelIdAndProviderId(Integer modelId, Integer providerId);
    List<ModelProvider> findByModelId(Integer modelId);
    List<ModelProvider> findByProviderId(Integer providerId);

    @Query(value = """
        SELECT m.id AS model_id, m.name AS model_name, mp.endpoint, mp.api_key
        FROM model_provider mp JOIN models m ON m.id = mp.model_id
        WHERE mp.provider_id = :providerId ORDER BY m.name ASC
        """, nativeQuery = true)
    List<ProviderModelProjection> findModelsForProvider(@Param("providerId") int providerId);

    /**
     * p50 latency figures (ms) over the successful, warm (non-cold-start)
     * requests of one model-provider pair inside the given window.
     * total = response - request, ttft = first_token - request.
     */
    @Query(value = """
        SELECT
            COUNT(*) FILTER (WHERE le.timestamp_response IS NOT NULL) AS samples,
            PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request)) * 1000
            ) FILTER (WHERE le.timestamp_response IS NOT NULL) AS total_p50_ms,
            PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (le.time_at_first_token - le.timestamp_request)) * 1000
            ) FILTER (WHERE le.time_at_first_token IS NOT NULL AND le.timestamp_response IS NOT NULL) AS ttft_p50_ms
        FROM log_entry le
        WHERE le.model_id = :modelId
          AND le.provider_id = :providerId
          AND le.result_status = 'success'
          AND COALESCE(le.was_cold_start, FALSE) = FALSE
          AND le.timestamp_request >= :since
        """, nativeQuery = true)
    PairLatencyStatsProjection findLatencyStats(@Param("modelId") int modelId,
                                                @Param("providerId") int providerId,
                                                @Param("since") Timestamp since);

    /**
     * p50 time-per-output-token (ms) over the same population: the generation
     * phase (first_token -> response) divided by the completion token count.
     * Needs at least 2 completion tokens to be meaningful.
     */
    @Query(value = """
        SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (le.timestamp_response - le.time_at_first_token)) * 1000
                   / GREATEST(ut.token_count - 1, 1)
        ) AS tpot_p50_ms
        FROM log_entry le
        JOIN usage_tokens ut ON ut.log_entry_id = le.id
        JOIN token_types tt ON tt.id = ut.type_id AND tt.name = 'completion_tokens'
        WHERE le.model_id = :modelId
          AND le.provider_id = :providerId
          AND le.result_status = 'success'
          AND COALESCE(le.was_cold_start, FALSE) = FALSE
          AND le.timestamp_request >= :since
          AND le.time_at_first_token IS NOT NULL
          AND le.timestamp_response IS NOT NULL
          AND ut.token_count >= 2
        """, nativeQuery = true)
    PairTpotStatsProjection findTpotStats(@Param("modelId") int modelId,
                                          @Param("providerId") int providerId,
                                          @Param("since") Timestamp since);

    /**
     * Latest valid catalogue prices (per-1K-token, micro-cents) for the pair,
     * with the same model+provider > model > provider > global specificity as
     * the billing queries.
     */
    @Query(value = """
        SELECT
            (SELECT tp.price_per_k_token
             FROM token_prices tp JOIN token_types tt ON tt.id = tp.type_id AND tt.name = 'prompt_tokens'
             WHERE (tp.model_id = :modelId OR tp.model_id IS NULL)
               AND (tp.provider_id = :providerId OR tp.provider_id IS NULL)
               AND tp.valid_from <= NOW()
             ORDER BY (tp.model_id = :modelId) DESC NULLS LAST,
                      (tp.provider_id = :providerId) DESC NULLS LAST,
                      tp.valid_from DESC
             LIMIT 1) AS input_price_per_k,
            (SELECT tp.price_per_k_token
             FROM token_prices tp JOIN token_types tt ON tt.id = tp.type_id AND tt.name = 'completion_tokens'
             WHERE (tp.model_id = :modelId OR tp.model_id IS NULL)
               AND (tp.provider_id = :providerId OR tp.provider_id IS NULL)
               AND tp.valid_from <= NOW()
             ORDER BY (tp.model_id = :modelId) DESC NULLS LAST,
                      (tp.provider_id = :providerId) DESC NULLS LAST,
                      tp.valid_from DESC
             LIMIT 1) AS output_price_per_k
        FROM model_provider mp
        WHERE mp.model_id = :modelId AND mp.provider_id = :providerId
        """, nativeQuery = true)
    PairTokenPriceProjection findTokenPrices(@Param("modelId") int modelId,
                                             @Param("providerId") int providerId);

    /**
     * Targeted update of the derived columns only, so a concurrent edit of the
     * pair's api_key/endpoint is never clobbered by the derivation.
     */
    @Transactional
    @Modifying
    @Query(value = """
        UPDATE model_provider
        SET derived_ttft_ms = :ttftMs,
            derived_total_latency_ms = :totalLatencyMs,
            derived_tpot_ms = :tpotMs,
            derived_cost_usd_per_million = :costUsdPerMillion,
            derived_samples = :samples,
            derived_updated_at = :updatedAt
        WHERE model_id = :modelId AND provider_id = :providerId
        """, nativeQuery = true)
    int updateDerivedMetrics(@Param("modelId") int modelId,
                             @Param("providerId") int providerId,
                             @Param("ttftMs") Integer ttftMs,
                             @Param("totalLatencyMs") Integer totalLatencyMs,
                             @Param("tpotMs") Integer tpotMs,
                             @Param("costUsdPerMillion") BigDecimal costUsdPerMillion,
                             @Param("samples") int samples,
                             @Param("updatedAt") Instant updatedAt);

    @Query(value = """
        SELECT mp.model_id AS model_id, m.name AS model_name,
               mp.provider_id AS provider_id, p.name AS provider_name,
               p.provider_type AS provider_type, p.cloud_provider_type AS cloud_provider_type,
               mp.derived_ttft_ms AS derived_ttft_ms,
               mp.derived_total_latency_ms AS derived_total_latency_ms,
               mp.derived_tpot_ms AS derived_tpot_ms,
               mp.derived_cost_usd_per_million AS derived_cost_usd_per_million,
               mp.derived_samples AS derived_samples,
               mp.derived_updated_at AS derived_updated_at
        FROM model_provider mp
        JOIN models m ON m.id = mp.model_id
        JOIN providers p ON p.id = mp.provider_id
        WHERE :modelId IS NULL OR mp.model_id = :modelId
        ORDER BY m.name ASC, p.name ASC
        """, nativeQuery = true)
    List<ModelPairMetricsProjection> findPairMetrics(@Param("modelId") Integer modelId);
}
