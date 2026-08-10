package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelCapabilities;

public interface ModelCapabilitiesRepository extends JpaRepository<ModelCapabilities, Integer> {
    Optional<ModelCapabilities> findByModelId(Integer modelId);
}