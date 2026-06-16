package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.transaction.annotation.Transactional;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ApiKeyProviderPermission;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ApiKeyProviderPermissionId;

public interface ApiKeyProviderPermissionRepository
        extends JpaRepository<ApiKeyProviderPermission, ApiKeyProviderPermissionId> {

    List<ApiKeyProviderPermission> findById_ApiKeyId(Integer apiKeyId);

    @Transactional
    void deleteById_ApiKeyId(Integer apiKeyId);
}
