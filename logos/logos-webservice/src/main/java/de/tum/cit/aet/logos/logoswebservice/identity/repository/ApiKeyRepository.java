package de.tum.cit.aet.logos.logoswebservice.identity.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.MyKeyProjection;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ModelAccessProjection;

public interface ApiKeyRepository extends JpaRepository<ApiKey, Integer> {
    Optional<ApiKey> findByKeyValueAndIsActiveTrue(String keyValue);

    long countByIsActive(boolean isActive);

    @Query(value = """
        SELECT COUNT(*) > 0 FROM api_keys ak
        JOIN users u ON ak.user_id = u.id
        WHERE ak.key_value = :keyValue AND u.role = 'logos_admin' AND ak.is_active = true
        """, nativeQuery = true)
    Boolean isLogosAdmin(@Param("keyValue") String keyValue);

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

    @Query(value = """
        SELECT
          ak.id,
          ak.key_value,
          ak.name,
          ak.key_type::text AS key_type,
          ak.environment,
          ak.log::text AS log,
          ak.use_custom_permissions,
          ak.settings::text AS settings_text,
          ak.team_id,
          t.name AS team_name,
          t.team_monthly_budget_micro_cents,
          COALESCE(bu.cost_micro_cents, 0) AS used_micro_cents,
          COALESCE((
              SELECT SUM(bu2.cost_micro_cents)
              FROM budget_usage bu2
              JOIN api_keys ak2 ON ak2.id = bu2.api_key_id
              WHERE ak2.team_id = ak.team_id
                AND bu2.month = DATE_TRUNC('month', CURRENT_DATE)::date
          ), 0) AS team_budget_used_micro_cents,
          (
              SELECT MAX(COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response))
              FROM log_entry le
              WHERE le.api_key_id = ak.id
          ) AS last_used_at
        FROM api_keys ak
        LEFT JOIN budget_usage bu
          ON bu.api_key_id = ak.id
          AND bu.month = DATE_TRUNC('month', CURRENT_DATE)::date
        LEFT JOIN teams t ON t.id = ak.team_id
        WHERE ak.user_id = :userId AND ak.is_active = true
        ORDER BY ak.id
        """, nativeQuery = true)
    List<MyKeyProjection> findKeysForUser(@Param("userId") int userId);

    @Query(value = """
        SELECT m.name AS model_name, p.name AS provider_name, p.privacy_level::text AS provider_type
        FROM team_model_permissions tmp
        JOIN model_provider mp ON mp.model_id = tmp.model_id
        JOIN models m ON m.id = mp.model_id
        JOIN providers p ON p.id = mp.provider_id
        JOIN team_provider_permissions tpp
          ON tpp.team_id = tmp.team_id AND tpp.provider_id = mp.provider_id
        WHERE tmp.team_id = :teamId
        ORDER BY m.name, p.name
        """, nativeQuery = true)
    List<ModelAccessProjection> findAccessibleModelsByTeam(@Param("teamId") int teamId);

    @Query(value = """
        SELECT m.name AS model_name, p.name AS provider_name, p.privacy_level::text AS provider_type
        FROM models m
        JOIN model_provider mp ON mp.model_id = m.id
        JOIN providers p ON p.id = mp.provider_id
        ORDER BY m.name, p.name
        """, nativeQuery = true)
    List<ModelAccessProjection> findAllModels();

    @Query(value = """
        SELECT m.name AS model_name, p.name AS provider_name, p.privacy_level::text AS provider_type
        FROM api_key_model_permissions akmp
        JOIN model_provider mp ON mp.model_id = akmp.model_id
        JOIN models m ON m.id = mp.model_id
        JOIN providers p ON p.id = mp.provider_id
        JOIN api_key_provider_permissions akpp
          ON akpp.api_key_id = akmp.api_key_id AND akpp.provider_id = mp.provider_id
        WHERE akmp.api_key_id = :keyId
        ORDER BY m.name, p.name
        """, nativeQuery = true)
    List<ModelAccessProjection> findAccessibleModelsByKey(@Param("keyId") int keyId);
}
