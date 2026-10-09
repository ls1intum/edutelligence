package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/**
 * Native SQL for gateway auth and permitted deployments.
 *
 * <p>The common cloud path uses {@link #authenticateAndFindDeploymentsForModel}
 * so authorization is a single round-trip: key lookup plus model and provider
 * permission joins. Model ids are resolved case-insensitively with planner /
 * replica aliases in Java ({@link GatewayModelNameResolver}).
 */
@Repository
public class GatewayDeploymentRepository {

    private static final String KEY_AND_DEPLOYMENTS_SQL = """
        WITH key_info AS (
            SELECT ak.id AS aki,
                   ak.key_value,
                   ak.name AS key_name,
                   ak.key_type::text AS key_type,
                   ak.team_id AS tid,
                   ak.user_id,
                   ak.environment,
                   ak.use_custom_permissions AS custom,
                   ak.settings::text AS settings_text,
                   ak.default_priority,
                   ak.log::text AS log_level
            FROM api_keys ak
            WHERE ak.key_value = :key_value
              AND ak.is_active = true
        ),
        effective_providers AS (
            SELECT akpp.provider_id
            FROM api_key_provider_permissions akpp, key_info ki
            WHERE akpp.api_key_id = ki.aki AND ki.custom = true
            UNION
            SELECT tpp.provider_id
            FROM team_provider_permissions tpp, key_info ki
            WHERE tpp.team_id = ki.tid AND ki.custom = false
        ),
        effective_models AS (
            SELECT akmp.model_id
            FROM api_key_model_permissions akmp, key_info ki
            WHERE akmp.api_key_id = ki.aki AND ki.custom = true
            UNION
            SELECT tmp.model_id
            FROM team_model_permissions tmp, key_info ki
            WHERE tmp.team_id = ki.tid AND ki.custom = false
        ),
        permitted AS (
            SELECT m.id AS model_id,
                   m.name AS model_name,
                   (SELECT string_agg(a.alias, ',' ORDER BY a.alias)
                      FROM model_aliases a WHERE a.model_id = m.id) AS aliases_csv,
                   p.id AS provider_id,
                   p.name AS provider_name,
                   p.provider_type AS provider_type,
                   p.cloud_provider_type AS cloud_provider_type,
                   p.base_url AS base_url,
                   mp.endpoint AS endpoint,
                   p.auth_name AS auth_name,
                   p.auth_format AS auth_format,
                   p.privacy_level::text AS privacy_level,
                   COALESCE(NULLIF(mp.api_key, ''), p.api_key, '') AS provider_api_key
            FROM effective_models em
                 JOIN models m ON m.id = em.model_id
                 JOIN model_provider mp ON m.id = mp.model_id
                 JOIN providers p ON mp.provider_id = p.id
                 JOIN effective_providers ep ON p.id = ep.provider_id
        )
        SELECT ki.aki AS api_key_id,
               ki.key_value,
               ki.key_name,
               ki.key_type,
               ki.tid AS team_id,
               ki.user_id,
               ki.environment,
               ki.custom AS use_custom_permissions,
               ki.settings_text,
               ki.default_priority,
               ki.log_level,
               d.model_id,
               d.model_name,
               d.aliases_csv,
               d.provider_id,
               d.provider_name,
               d.provider_type,
               d.cloud_provider_type,
               d.base_url,
               d.endpoint,
               d.auth_name,
               d.auth_format,
               d.privacy_level,
               d.provider_api_key
        FROM key_info ki
             LEFT JOIN permitted d ON true
        ORDER BY d.provider_id NULLS LAST
        """;

    private static final String KEY_ONLY_SQL = """
        SELECT ak.id AS api_key_id,
               ak.key_value,
               ak.name AS key_name,
               ak.key_type::text AS key_type,
               ak.team_id,
               ak.user_id,
               ak.environment,
               ak.use_custom_permissions,
               ak.settings::text AS settings_text,
               ak.default_priority,
               ak.log::text AS log_level
        FROM api_keys ak
        WHERE ak.key_value = :key_value
          AND ak.is_active = true
        """;

    private final NamedParameterJdbcTemplate jdbc;

    public GatewayDeploymentRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * One round-trip: authenticate the key and load permitted deployments for
     * {@code modelName} (canonical name, alias, planner-safe, or replica id).
     * Empty optional → invalid key. Present with an empty deployment list →
     * key valid but no permitted deployment for that model.
     */
    public Optional<GatewayAuthContext> authenticateAndFindDeploymentsForModel(
            String keyValue, String modelName) {
        MapSqlParameterSource params = new MapSqlParameterSource("key_value", keyValue);
        List<GatewayAuthContext> rows = jdbc.query(KEY_AND_DEPLOYMENTS_SQL, params, rs -> {
            GatewayKey key = null;
            List<GatewayDeployment> all = new ArrayList<>();
            while (rs.next()) {
                if (key == null) {
                    key = mapKey(rs);
                }
                Integer modelId = (Integer) rs.getObject("model_id");
                Integer providerId = (Integer) rs.getObject("provider_id");
                if (modelId != null && providerId != null) {
                    all.add(mapDeployment(rs, modelId, providerId));
                }
            }
            if (key == null) {
                return List.of();
            }
            return List.of(new GatewayAuthContext(key, filterByResolvedModel(all, modelName)));
        });
        return rows.isEmpty() ? Optional.empty() : Optional.of(rows.get(0));
    }

    /** Authenticate only (listing / jobs / resource-mode / proxy-all). */
    public Optional<GatewayKey> findActiveKey(String keyValue) {
        MapSqlParameterSource params = new MapSqlParameterSource("key_value", keyValue);
        List<GatewayKey> keys = jdbc.query(KEY_ONLY_SQL, params, (rs, rowNum) -> mapKey(rs));
        return keys.stream().findFirst();
    }

    /**
     * Permitted deployments for an already-authenticated key id.
     */
    public List<GatewayDeployment> findPermittedDeploymentsForModel(int apiKeyId, String modelName) {
        MapSqlParameterSource params = new MapSqlParameterSource("api_key_id", apiKeyId);
        List<GatewayDeployment> all = jdbc.query("""
            WITH key_info AS (
                SELECT ak.id AS aki,
                       ak.team_id AS tid,
                       ak.use_custom_permissions AS custom
                FROM api_keys ak
                WHERE ak.id = :api_key_id
                  AND ak.is_active = true
            ),
            effective_providers AS (
                SELECT akpp.provider_id
                FROM api_key_provider_permissions akpp, key_info ki
                WHERE akpp.api_key_id = ki.aki AND ki.custom = true
                UNION
                SELECT tpp.provider_id
                FROM team_provider_permissions tpp, key_info ki
                WHERE tpp.team_id = ki.tid AND ki.custom = false
            ),
            effective_models AS (
                SELECT akmp.model_id
                FROM api_key_model_permissions akmp, key_info ki
                WHERE akmp.api_key_id = ki.aki AND ki.custom = true
                UNION
                SELECT tmp.model_id
                FROM team_model_permissions tmp, key_info ki
                WHERE tmp.team_id = ki.tid AND ki.custom = false
            )
            SELECT m.id AS model_id,
                   m.name AS model_name,
                   (SELECT string_agg(a.alias, ',' ORDER BY a.alias)
                      FROM model_aliases a WHERE a.model_id = m.id) AS aliases_csv,
                   p.id AS provider_id,
                   p.name AS provider_name,
                   p.provider_type AS provider_type,
                   p.cloud_provider_type AS cloud_provider_type,
                   p.base_url AS base_url,
                   mp.endpoint AS endpoint,
                   p.auth_name AS auth_name,
                   p.auth_format AS auth_format,
                   p.privacy_level::text AS privacy_level,
                   COALESCE(NULLIF(mp.api_key, ''), p.api_key, '') AS provider_api_key
            FROM models m
                 JOIN effective_models em ON m.id = em.model_id
                 JOIN model_provider mp ON m.id = mp.model_id
                 JOIN providers p ON mp.provider_id = p.id
                 JOIN effective_providers ep ON p.id = ep.provider_id
            ORDER BY p.id
            """, params, (rs, rowNum) -> mapDeployment(
                rs, rs.getInt("model_id"), rs.getInt("provider_id")));
        return filterByResolvedModel(all, modelName);
    }

    /**
     * Team default cloud RPM/TPM. Returns {@code int[2]} where a negative
     * value means SQL NULL (no default).
     */
    public int[] findTeamCloudRateLimits(int teamId) {
        MapSqlParameterSource params = new MapSqlParameterSource("tid", teamId);
        return jdbc.query("""
            SELECT default_cloud_rpm_limit, default_cloud_tpm_limit
            FROM teams WHERE id = :tid
            """, params, rs -> {
            if (!rs.next()) {
                return new int[] {-1, -1};
            }
            int rpm = rs.getInt(1);
            if (rs.wasNull()) {
                rpm = -1;
            }
            int tpm = rs.getInt(2);
            if (rs.wasNull()) {
                tpm = -1;
            }
            return new int[] {rpm, tpm};
        });
    }

    static List<GatewayDeployment> filterByResolvedModel(List<GatewayDeployment> all, String modelName) {
        if (all == null || all.isEmpty()) {
            return List.of();
        }
        Map<Integer, GatewayModelNameResolver.ModelNames> byId = new LinkedHashMap<>();
        for (GatewayDeployment d : all) {
            byId.putIfAbsent(d.modelId(), GatewayModelNameResolver.ModelNames.of(d.modelName(), d.aliasesCsv()));
        }
        String resolved = GatewayModelNameResolver.resolve(modelName, List.copyOf(byId.values()));
        if (resolved == null) {
            return List.of();
        }
        List<GatewayDeployment> filtered = new ArrayList<>();
        for (GatewayDeployment d : all) {
            if (resolved.equals(d.modelName())) {
                filtered.add(d);
            }
        }
        return List.copyOf(filtered);
    }

    private static GatewayKey mapKey(ResultSet rs) throws SQLException {
        return new GatewayKey(
            rs.getInt("api_key_id"),
            rs.getString("key_value"),
            rs.getString("key_name"),
            ApiKeyType.valueOf(rs.getString("key_type")),
            (Integer) rs.getObject("team_id"),
            (Integer) rs.getObject("user_id"),
            rs.getString("environment"),
            rs.getBoolean("use_custom_permissions"),
            rs.getString("settings_text"),
            rs.getInt("default_priority"),
            rs.getString("log_level")
        );
    }

    private static GatewayDeployment mapDeployment(ResultSet rs, int modelId, int providerId)
            throws SQLException {
        return new GatewayDeployment(
            modelId,
            rs.getString("model_name"),
            providerId,
            rs.getString("provider_name"),
            rs.getString("provider_type"),
            rs.getString("cloud_provider_type"),
            rs.getString("base_url"),
            rs.getString("endpoint"),
            rs.getString("auth_name"),
            rs.getString("auth_format"),
            rs.getString("provider_api_key"),
            rs.getString("privacy_level"),
            rs.getString("aliases_csv")
        );
    }
}
