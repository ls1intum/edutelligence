package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApplicationKeyQueueRank;

public interface ApplicationKeyQueueRankRepository extends JpaRepository<ApplicationKeyQueueRank, Integer> {
    List<ApplicationKeyQueueRank> findAllByOrderByRankAsc();
}
