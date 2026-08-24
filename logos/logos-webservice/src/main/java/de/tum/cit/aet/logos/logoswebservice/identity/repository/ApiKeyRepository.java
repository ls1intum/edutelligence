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
          t.default_cloud_rpm_limit AS team_default_cloud_rpm_limit,
          t.default_cloud_tpm_limit AS team_default_cloud_tpm_limit,
          t.default_local_rpm_limit AS team_default_local_rpm_limit,
          t.default_local_tpm_limit AS team_default_local_tpm_limit,
          t.default_monthly_budget_micro_cents AS team_default_monthly_budget_micro_cents,
          COALESCE(bu.cost_micro_cents, 0) AS used_micro_cents,
          COALESCE(team_bu.cost_micro_cents, 0) AS team_budget_used_micro_cents,
          (
              SELECT MAX(COALESCE(le.timestamp_forwarding, le.timestamp_request, le.timestamp_response))
              FROM log_entry le
              WHERE le.api_key_id = ak.id
          ) AS last_used_at
        FROM api_keys ak
        -- Per-key spend, restricted up front to this user's own key ids instead of
        -- going through the budget_usage view (which groups the entire platform's
        -- log_entry/usage_tokens by api_key_id before anything can be filtered).
        -- Same grouping column and predicates as the view, just scoped early so
        -- Postgres can use idx_log_entry_api_key_id instead of scanning everyone's
        -- current-month usage to find this user's few keys.
        LEFT JOIN (
            SELECT le.api_key_id, COALESCE(SUM(
                CASE WHEN tp.price_per_k_token IS NOT NULL
                    THEN (ut.token_count::BIGINT * tp.price_per_k_token / 1000)::BIGINT
                    ELSE 0
                END
            ), 0) AS cost_micro_cents
            FROM log_entry le
            JOIN usage_tokens ut ON ut.log_entry_id = le.id
            LEFT JOIN LATERAL (
                SELECT price_per_k_token
                FROM token_prices
                WHERE type_id = ut.type_id
                  AND (model_id = le.model_id OR model_id IS NULL)
                  AND (provider_id = le.provider_id OR provider_id IS NULL)
                  AND valid_from <= le.timestamp_request
                ORDER BY (model_id = le.model_id) DESC NULLS LAST,
                         (provider_id = le.provider_id) DESC NULLS LAST,
                         valid_from DESC
                LIMIT 1
            ) tp ON true
            WHERE le.api_key_id IN (
                SELECT id FROM api_keys WHERE user_id = :userId AND is_active = true
            )
            AND DATE_TRUNC('month', le.timestamp_request)::date = DATE_TRUNC('month', CURRENT_DATE)::date
            GROUP BY le.api_key_id
        ) bu ON bu.api_key_id = ak.id
        LEFT JOIN teams t ON t.id = ak.team_id
        -- Team spend, computed once per request (not once per key). Attributed via
        -- api_keys.team_id (ak2), matching the old budget_usage-based subquery
        -- exactly -- log_entry.team_id itself cannot be used as the filter here:
        -- it's nullable (ON DELETE SET NULL) and can disagree with the owning
        -- key's current team, so filtering on it directly under-counts spend.
        -- Restricting ak2 up front to this user's own team(s) still avoids
        -- re-aggregating the entire platform's log_entry/usage_tokens history once
        -- per key the user owns. Scoped to developer keys only, matching
        -- get_team_budget_usage in the orchestrator: application keys carry
        -- their own separate budget and never count against the team cap.
        LEFT JOIN (
            SELECT ak2.team_id, COALESCE(SUM(
                CASE WHEN tp.price_per_k_token IS NOT NULL
                    THEN (ut.token_count::BIGINT * tp.price_per_k_token / 1000)::BIGINT
                    ELSE 0
                END
            ), 0) AS cost_micro_cents
            FROM log_entry le
            JOIN usage_tokens ut ON ut.log_entry_id = le.id
            JOIN api_keys ak2 ON ak2.id = le.api_key_id
            LEFT JOIN LATERAL (
                SELECT price_per_k_token
                FROM token_prices
                WHERE type_id = ut.type_id
                  AND (model_id = le.model_id OR model_id IS NULL)
                  AND (provider_id = le.provider_id OR provider_id IS NULL)
                  AND valid_from <= le.timestamp_request
                ORDER BY (model_id = le.model_id) DESC NULLS LAST,
                         (provider_id = le.provider_id) DESC NULLS LAST,
                         valid_from DESC
                LIMIT 1
            ) tp ON true
            WHERE ak2.team_id IN (
                SELECT DISTINCT team_id FROM api_keys
                WHERE user_id = :userId AND is_active = true AND team_id IS NOT NULL
            )
            AND ak2.key_type = 'developer'
            AND DATE_TRUNC('month', le.timestamp_request)::date = DATE_TRUNC('month', CURRENT_DATE)::date
            GROUP BY ak2.team_id
        ) team_bu ON team_bu.team_id = ak.team_id
        WHERE ak.user_id = :userId AND ak.is_active = true
        ORDER BY ak.id
        """, nativeQuery = true)
    List<MyKeyProjection> findKeysForUser(@Param("userId") int userId);

    @Query(value = """
        SELECT m.name AS model_name, p.name AS provider_name, p.provider_type::text AS provider_type
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
        SELECT m.name AS model_name, p.name AS provider_name, p.provider_type::text AS provider_type
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

    List<ApiKey> findByUserIdAndTeamIdAndKeyType(Integer userId, Integer teamId, ApiKeyType keyType);

    List<ApiKey> findByUserIdAndTeamIdIsNullAndKeyType(Integer userId, ApiKeyType keyType);

    List<ApiKey> findByUserIdAndIsActiveTrue(Integer userId);

    List<ApiKey> findByUserIdAndIsActiveTrueOrderByIdAsc(Integer userId);

    List<ApiKey> findByUserId(Integer userId);
}
