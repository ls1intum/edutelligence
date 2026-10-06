package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;

import jakarta.persistence.LockModeType;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;

public interface TeamRepository extends JpaRepository<Team, Integer> {

    @Query("""
        SELECT DISTINCT t FROM Team t
        JOIN TeamMember tm ON tm.id.teamId = t.id
        WHERE tm.id.userId = :userId
        """)
    List<Team> findTeamsForUser(@Param("userId") Integer userId);

    Optional<Team> findByName(String name);

    Optional<Team> findFirstByName(String name);

    List<Team> findByKeycloakGroupIsNotNull();

    Optional<Team> findByKeycloakGroup(String keycloakGroup);

    /**
     * Locked read for every mutation of a team row.
     *
     * <p>The team endpoints each write the whole row, so without a lock the
     * last writer wins on fields it never touched: a limits save that read the
     * team before its Keycloak group was removed would put that group back,
     * letting an app_admin owner undo a link decision only logos_admins may
     * make — and the membership cleanup that ran with the removal would not
     * run again. Taking this lock before every team write serializes them.
     * Callers must run inside a transaction.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT t FROM Team t WHERE t.id = :id")
    Optional<Team> findByIdForUpdate(@Param("id") Integer id);

    /**
     * Locks a team row and reports the Keycloak group it currently carries.
     *
     * <p>Deliberately a scalar, not the entity: the login sync has already
     * loaded the team while resolving it, and a locked entity read would hand
     * back that cached copy with the link the sync saw before waiting, which is
     * exactly the stale value the lock is there to rule out. An empty result
     * means the team has no link any more, or no longer exists — the caller
     * treats both as "do not join".
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT t.keycloakGroup FROM Team t WHERE t.id = :id")
    Optional<String> lockAndReadKeycloakGroup(@Param("id") Integer id);
}
