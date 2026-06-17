package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

public interface ApiKeyRepository extends JpaRepository<ApiKey, Integer> {
    Optional<ApiKey> findByKeyValueAndIsActiveTrue(String keyValue);

    long countByIsActive(boolean isActive);

    boolean existsByTeamIdAndKeyTypeAndEnvironmentAndIsActive(
            Integer teamId, ApiKeyType keyType, String environment, boolean isActive);

    @Query(value = """
        SELECT id, key_value, name, key_type::text AS key_type, user_id, environment,
               log::text AS log,
               settings::text AS settings_text, default_priority, is_active,
               use_custom_permissions,
               COALESCE((SELECT cost_micro_cents FROM budget_usage
                         WHERE api_key_id = api_keys.id
                           AND month = DATE_TRUNC('month', CURRENT_DATE)::date), 0) AS used_micro_cents
        FROM api_keys WHERE team_id = :teamId AND is_active = true ORDER BY id
        """, nativeQuery = true)
    List<ApiKeyWithBudgetProjection> findKeysForTeam(@Param("teamId") int teamId);

    List<ApiKey> findByUserIdAndTeamIdAndKeyType(Integer userId, Integer teamId, ApiKeyType keyType);

    List<ApiKey> findByUserIdAndTeamIdIsNullAndKeyType(Integer userId, ApiKeyType keyType);

    List<ApiKey> findByUserIdAndIsActiveTrue(Integer userId);

    List<ApiKey> findByUserIdAndIsActiveTrueOrderByIdAsc(Integer userId);

    List<ApiKey> findByUserId(Integer userId);
}
