package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelProvider;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ModelProviderBenchmarkProjection;

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
        SELECT m.id AS model_id, m.name AS model_name, mp.endpoint, mp.api_key
        FROM model_provider mp JOIN models m ON m.id = mp.model_id
        WHERE mp.provider_id = :providerId ORDER BY m.name ASC
        """, nativeQuery = true)
    List<ProviderModelProjection> findModelsForProvider(@Param("providerId") int providerId);
}
