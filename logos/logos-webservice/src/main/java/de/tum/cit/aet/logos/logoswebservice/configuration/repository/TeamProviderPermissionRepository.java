package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.transaction.annotation.Transactional;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TeamProviderPermission;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TeamProviderPermissionId;

public interface TeamProviderPermissionRepository
        extends JpaRepository<TeamProviderPermission, TeamProviderPermissionId> {

    List<TeamProviderPermission> findById_TeamId(Integer teamId);

    @Transactional
    void deleteById_TeamId(Integer teamId);
}
