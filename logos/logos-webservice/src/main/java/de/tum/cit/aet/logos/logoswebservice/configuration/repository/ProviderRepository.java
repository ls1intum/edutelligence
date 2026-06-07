package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Provider;

public interface ProviderRepository extends JpaRepository<Provider, Integer> {}