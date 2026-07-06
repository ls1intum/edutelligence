package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ApiKeyModelPermission;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ApiKeyModelPermissionId;

public interface ApiKeyModelPermissionRepository
        extends JpaRepository<ApiKeyModelPermission, ApiKeyModelPermissionId> {

    List<ApiKeyModelPermission> findById_ApiKeyId(Integer apiKeyId);

    @Transactional
    void deleteById_ApiKeyId(Integer apiKeyId);

    @Transactional
    @Modifying
    @Query(value = """
        DELETE FROM api_key_model_permissions
        WHERE api_key_id = :keyId
          AND model_id NOT IN (
              SELECT DISTINCT mp.model_id FROM model_provider mp
              JOIN api_key_provider_permissions akpp ON mp.provider_id = akpp.provider_id
              WHERE akpp.api_key_id = :keyId
          )
        """, nativeQuery = true)
    void deleteCascadeForApiKey(@Param("keyId") int keyId);
}
