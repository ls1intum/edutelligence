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
}
