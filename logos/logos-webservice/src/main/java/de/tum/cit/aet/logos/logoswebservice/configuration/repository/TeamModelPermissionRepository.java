package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TeamModelPermission;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TeamModelPermissionId;

public interface TeamModelPermissionRepository
        extends JpaRepository<TeamModelPermission, TeamModelPermissionId> {

    List<TeamModelPermission> findById_TeamId(Integer teamId);

    long countById_TeamId(Integer teamId);

    @Transactional
    void deleteById_TeamId(Integer teamId);

    @Transactional
    @Modifying
    @Query(value = """
        DELETE FROM team_model_permissions
        WHERE team_id = :teamId
          AND model_id NOT IN (
              SELECT DISTINCT mp.model_id FROM model_provider mp
              JOIN team_provider_permissions tpp ON mp.provider_id = tpp.provider_id
              WHERE tpp.team_id = :teamId
          )
        """, nativeQuery = true)
    void deleteCascadeForTeam(@Param("teamId") int teamId);

    /**
     * The full team access matrix for one model in a single query: every
     * team crossed with every hosting provider, each side left-joined so a
     * missing grant reads as "not granted" instead of dropping the row.
     * A model without hosting providers yields one row per team with
     * provider_id null — those teams' model grants are all orphaned.
     */
    @Query(value = """
        SELECT t.id AS teamId,
               t.name AS teamName,
               (tmp.model_id IS NOT NULL) AS modelGrant,
               mp.provider_id AS providerId,
               (tpp.provider_id IS NOT NULL) AS providerGrant
        FROM teams t
        LEFT JOIN model_provider mp ON mp.model_id = :modelId
        LEFT JOIN team_model_permissions tmp
               ON tmp.team_id = t.id AND tmp.model_id = :modelId
        LEFT JOIN team_provider_permissions tpp
               ON tpp.team_id = t.id AND tpp.provider_id = mp.provider_id
        ORDER BY t.id, mp.provider_id NULLS LAST
        """, nativeQuery = true)
    List<ModelAccessMatrixProjection> findModelAccessMatrix(@Param("modelId") Integer modelId);
}
