package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TokenType;

public interface TokenTypeRepository extends JpaRepository<TokenType, Integer> {
    Optional<TokenType> findByName(String name);
}
