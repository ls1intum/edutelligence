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
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ModelProviderBenchmarkProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ModelBenchmarkJobProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ModelBenchmarkTargetProjection;

public interface ModelProviderRepository extends JpaRepository<ModelProvider, Integer> {
    Optional<ModelProvider> findByModelIdAndProviderId(Integer modelId, Integer providerId);
    void deleteByModelIdAndProviderId(Integer modelId, Integer providerId);
    List<ModelProvider> findByModelId(Integer modelId);
    List<ModelProvider> findByProviderId(Integer providerId);

    @Query(value = """
        SELECT b.id,
               b.model_provider_id AS modelProviderId,
               p.id AS providerId,
               p.name AS providerName,
               m.id AS modelId,
               m.name AS modelName,
               b.configuration::text AS configurationJson,
               b.dataset,
               b.sample_size AS sampleSize,
               b.metrics::text AS metricsJson,
               b.recorded_at AS recordedAt
        FROM model_provider_benchmarks b
        JOIN model_provider mp ON mp.id = b.model_provider_id
        JOIN providers p ON p.id = mp.provider_id
        JOIN models m ON m.id = mp.model_id
        WHERE m.id = :modelId
        ORDER BY b.recorded_at DESC, b.id DESC
        """, nativeQuery = true)
    List<ModelProviderBenchmarkProjection> findBenchmarksForModel(@Param("modelId") int modelId);

    @Query(value = """
        SELECT mp.id AS modelProviderId,
               p.id AS providerId,
               p.name AS providerName,
               p.provider_type AS providerType,
               m.id AS modelId,
               m.name AS modelName,
               (p.provider_type = 'logosnode' OR
                COALESCE(NULLIF(mp.endpoint, ''), NULLIF(p.base_url, '')) IS NOT NULL) AS endpointConfigured,
               (p.provider_type = 'logosnode' OR
                COALESCE(NULLIF(mp.api_key, ''), NULLIF(p.api_key, '')) IS NOT NULL) AS authenticationConfigured
        FROM model_provider mp
        JOIN providers p ON p.id = mp.provider_id
        JOIN models m ON m.id = mp.model_id
        WHERE m.id = :modelId
        ORDER BY p.name ASC, mp.id ASC
        """, nativeQuery = true)
    List<ModelBenchmarkTargetProjection> findBenchmarkTargetsForModel(@Param("modelId") int modelId);

    @Query(value = """
        SELECT j.id,
               j.status::text AS status,
               j.request_payload::text AS requestPayloadJson,
               j.result_payload::text AS resultPayloadJson,
               j.error_message AS errorMessage,
               j.created_at AS createdAt,
               j.updated_at AS updatedAt
        FROM jobs j
        WHERE j.environment = 'model-provider-benchmark'
          AND (j.request_payload ->> 'model_id')::integer = :modelId
        ORDER BY j.created_at DESC
        LIMIT 20
        """, nativeQuery = true)
    List<ModelBenchmarkJobProjection> findBenchmarkJobsForModel(@Param("modelId") int modelId);

    @Modifying
    @Transactional
    @Query(value = """
        INSERT INTO model_provider_benchmarks
            (model_provider_id, configuration, dataset, sample_size, metrics, recorded_at)
        VALUES
            (:modelProviderId, CAST(:configurationJson AS jsonb), :dataset, :sampleSize,
             CAST(:metricsJson AS jsonb), COALESCE(:recordedAt, CURRENT_TIMESTAMP))
        """, nativeQuery = true)
    int insertBenchmark(@Param("modelProviderId") int modelProviderId,
                        @Param("configurationJson") String configurationJson,
                        @Param("dataset") String dataset,
                        @Param("sampleSize") int sampleSize,
                        @Param("metricsJson") String metricsJson,
                        @Param("recordedAt") Instant recordedAt);

    @Modifying
    @Transactional
    @Query(value = "DELETE FROM model_provider_benchmarks WHERE id = :benchmarkId", nativeQuery = true)
    int deleteBenchmark(@Param("benchmarkId") int benchmarkId);

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
     * Latest currently-valid catalogue prices (per-1K-token, micro-cents) for
     * the pair, with the same model+provider > model > provider > global
     * specificity as the billing queries. Rows whose validity was closed (by
     * a provider type change) are not eligible, so the cost is only derived
     * from a price generation opened for the provider's current type.
     */
    @Query(value = """
        SELECT
            (SELECT tp.price_per_k_token
             FROM token_prices tp JOIN token_types tt ON tt.id = tp.type_id AND tt.name = 'prompt_tokens'
             WHERE (tp.model_id = :modelId OR tp.model_id IS NULL)
               AND (tp.provider_id = :providerId OR tp.provider_id IS NULL)
               AND tp.valid_from <= NOW()
               AND (tp.valid_to IS NULL OR tp.valid_to > NOW())
             ORDER BY (tp.model_id = :modelId) DESC NULLS LAST,
                      (tp.provider_id = :providerId) DESC NULLS LAST,
                      tp.valid_from DESC
             LIMIT 1) AS input_price_per_k,
            (SELECT tp.price_per_k_token
             FROM token_prices tp JOIN token_types tt ON tt.id = tp.type_id AND tt.name = 'completion_tokens'
             WHERE (tp.model_id = :modelId OR tp.model_id IS NULL)
               AND (tp.provider_id = :providerId OR tp.provider_id IS NULL)
               AND tp.valid_from <= NOW()
               AND (tp.valid_to IS NULL OR tp.valid_to > NOW())
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
            derived_cost_usd = :costUsd,
            derived_samples = :samples,
            derived_updated_at = :updatedAt
        WHERE model_id = :modelId AND provider_id = :providerId
        """, nativeQuery = true)
    int updateDerivedMetrics(@Param("modelId") int modelId,
                             @Param("providerId") int providerId,
                             @Param("ttftMs") Integer ttftMs,
                             @Param("totalLatencyMs") Integer totalLatencyMs,
                             @Param("tpotMs") Integer tpotMs,
                             @Param("costUsd") BigDecimal costUsd,
                             @Param("samples") int samples,
                             @Param("updatedAt") Instant updatedAt);

    /**
     * Clear the derived cost of every pair of the given provider, leaving the
     * unit-independent latency figures in place. The cost unit depends on the
     * provider's cloud_provider_type (USD per million tokens for cloud pairs,
     * USD per request for local pairs), so a type change invalidates every
     * persisted cost value: until the pairs are re-derived, a ranking that
     * reads the row must see NULL, or an old-unit value would be
     * reinterpreted in the new unit.
     */
    @Transactional
    @Modifying
    @Query(value = "UPDATE model_provider SET derived_cost_usd = NULL WHERE provider_id = :providerId",
           nativeQuery = true)
    int invalidateDerivedCostByProviderId(@Param("providerId") int providerId);

    @Query(value = """
        SELECT mp.model_id AS model_id, m.name AS model_name,
               mp.provider_id AS provider_id, p.name AS provider_name,
               p.provider_type AS provider_type, p.cloud_provider_type AS cloud_provider_type,
               mp.derived_ttft_ms AS derived_ttft_ms,
               mp.derived_total_latency_ms AS derived_total_latency_ms,
               mp.derived_tpot_ms AS derived_tpot_ms,
               mp.derived_cost_usd AS derived_cost_usd,
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
