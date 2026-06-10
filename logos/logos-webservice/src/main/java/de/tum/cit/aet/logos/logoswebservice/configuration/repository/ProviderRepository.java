package de.tum.cit.aet.logos.logoswebservice.configuration.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Provider;

public interface ProviderRepository extends JpaRepository<Provider, Integer> {

    List<Provider> findByCloudProviderTypeIsNotNull();

    @Query(value = """
        SELECT id, name, base_url, api_key, provider_type::text, cloud_provider_type::text,
               privacy_level::text, auth_name, auth_format
        FROM providers ORDER BY name ASC, id ASC
        """, nativeQuery = true)
    List<ProviderProjection> findAllForAdmin();

    @Query(value = """
        WITH key_info AS (
            SELECT ak.id AS aki, ak.team_id AS tid, ak.use_custom_permissions AS custom
            FROM api_keys ak WHERE ak.key_value = :keyValue AND ak.is_active = true
        ),
        effective_providers AS (
            SELECT akpp.provider_id FROM api_key_provider_permissions akpp, key_info ki
            WHERE akpp.api_key_id = ki.aki AND ki.custom = true
            UNION
            SELECT tpp.provider_id FROM team_provider_permissions tpp, key_info ki
            WHERE tpp.team_id = ki.tid AND ki.custom = false
        )
        SELECT DISTINCT p.id, p.name, p.base_url, p.api_key, p.provider_type::text,
               p.cloud_provider_type::text, p.privacy_level::text, p.auth_name, p.auth_format
        FROM providers p JOIN effective_providers ep ON p.id = ep.provider_id
        ORDER BY p.name ASC
        """, nativeQuery = true)
    List<ProviderProjection> findAllForKey(@Param("keyValue") String keyValue);
}
