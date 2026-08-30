package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.UserPasskey;

public interface UserPasskeyRepository extends JpaRepository<UserPasskey, Long> {

    List<UserPasskey> findByUserIdOrderByCreatedAtAsc(Integer userId);

    boolean existsByCredentialId(String credentialId);

    long countByUserId(Integer userId);
}
