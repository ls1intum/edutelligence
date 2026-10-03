package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamRepositoryCredential;

public interface TeamRepositoryCredentialRepository extends JpaRepository<TeamRepositoryCredential, Integer> {
    Optional<TeamRepositoryCredential> findByTeamRepositoryIdAndRevokedAtIsNull(Integer teamRepositoryId);
}
