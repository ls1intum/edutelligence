package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamRepoLink;
import jakarta.persistence.LockModeType;

public interface TeamRepoLinkRepository extends JpaRepository<TeamRepoLink, Integer> {

    List<TeamRepoLink> findByTeamIdOrderByRepoSlugAsc(Integer teamId);

    Optional<TeamRepoLink> findByIdAndTeamId(Integer id, Integer teamId);

    /**
     * Locks the link row for the surrounding transaction so slug invalidation
     * serializes with analysis ingest ({@code SELECT … FOR UPDATE} on the same id).
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT l FROM TeamRepoLink l WHERE l.id = :id AND l.teamId = :teamId")
    Optional<TeamRepoLink> findByIdAndTeamIdForUpdate(@Param("id") Integer id,
                                                      @Param("teamId") Integer teamId);

    boolean existsByTeamIdAndRepoSlug(Integer teamId, String repoSlug);

    boolean existsByTeamIdAndRepoSlugAndIdNot(Integer teamId, String repoSlug, Integer id);
}
