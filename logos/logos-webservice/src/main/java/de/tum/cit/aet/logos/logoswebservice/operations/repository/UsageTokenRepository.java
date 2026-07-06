package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.entity.UsageToken;

public interface UsageTokenRepository extends JpaRepository<UsageToken, Integer> {
}
