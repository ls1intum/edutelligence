package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

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
               (COALESCE(NULLIF(mp.endpoint, ''), NULLIF(p.base_url, '')) IS NOT NULL) AS endpointConfigured,
               (COALESCE(NULLIF(mp.api_key, ''), NULLIF(p.api_key, '')) IS NOT NULL) AS authenticationConfigured
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
}
