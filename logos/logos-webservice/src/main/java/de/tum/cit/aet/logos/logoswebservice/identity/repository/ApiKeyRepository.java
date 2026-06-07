package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;

public interface ApiKeyRepository extends JpaRepository<ApiKey, Integer> {
    Optional<ApiKey> findByKeyValueAndIsActiveTrue(String keyValue);
}
