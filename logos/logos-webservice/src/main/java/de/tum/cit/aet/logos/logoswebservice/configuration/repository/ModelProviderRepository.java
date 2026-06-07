package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelProvider;

public interface ModelProviderRepository extends JpaRepository<ModelProvider, Integer> {
    Optional<ModelProvider> findByModelIdAndProviderId(Integer modelId, Integer providerId);
    void deleteByModelIdAndProviderId(Integer modelId, Integer providerId);
}
