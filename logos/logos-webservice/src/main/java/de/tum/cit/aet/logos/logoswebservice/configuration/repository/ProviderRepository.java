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
        SELECT DISTINCT p.id, p.name, p.base_url, p.api_key, p.provider_type::text,
               p.cloud_provider_type::text, p.privacy_level::text, p.auth_name, p.auth_format
        FROM providers p
        JOIN team_provider_permissions tpp ON p.id = tpp.provider_id
        JOIN team_members tm ON tpp.team_id = tm.team_id
        WHERE tm.user_id = :userId
        ORDER BY p.name ASC
        """, nativeQuery = true)
    List<ProviderProjection> findAllForUser(@Param("userId") Integer userId);
}
