package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TeamProviderPermission;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TeamProviderPermissionId;

public interface TeamProviderPermissionRepository
        extends JpaRepository<TeamProviderPermission, TeamProviderPermissionId> {

    List<TeamProviderPermission> findById_TeamId(Integer teamId);

    @Transactional
    void deleteById_TeamId(Integer teamId);

    /**
     * Idempotent single-grant insert: adds this one team-provider row without
     * reading or replacing the team's other grants, so a concurrent permission
     * edit can neither be overwritten nor trigger the model-grant cascade.
     */
    @Transactional
    @Modifying
    @Query(value = """
        INSERT INTO team_provider_permissions (team_id, provider_id)
        VALUES (:teamId, :providerId)
        ON CONFLICT DO NOTHING
        """, nativeQuery = true)
    void grantIfAbsent(@Param("teamId") int teamId, @Param("providerId") int providerId);

    /**
     * Atomic single-grant removal (model access page): deletes exactly this
     * one team-provider row. Like grantIfAbsent it never reads or replaces the
     * team's other grants, so a concurrent permission edit cannot be undone by
     * a stale client snapshot. The model-grant cascade is applied by the
     * caller (PermissionService) in the same transaction.
     */
    @Transactional
    @Modifying
    @Query(value = """
        DELETE FROM team_provider_permissions
        WHERE team_id = :teamId AND provider_id = :providerId
        """, nativeQuery = true)
    void revoke(@Param("teamId") int teamId, @Param("providerId") int providerId);
}
