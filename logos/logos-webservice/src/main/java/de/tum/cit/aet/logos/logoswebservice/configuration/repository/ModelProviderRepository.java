package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

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
}
