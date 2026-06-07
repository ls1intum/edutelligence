package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateAppKeyRequest;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateApiKeyRequest;

@Service
public class ApiKeyAdminService {

    private static final SecureRandom SECURE_RANDOM = new SecureRandom();
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final JdbcTemplate jdbcTemplate;

    public ApiKeyAdminService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<Map<String, Object>> getKeysForTeam(int teamId) {
        return jdbcTemplate.query("""
            SELECT id, key_value, name, key_type, user_id, environment, log,
                   settings::text AS settings_text, default_priority, is_active,
                   use_custom_permissions,
                   COALESCE((SELECT cost_micro_cents FROM budget_usage
                             WHERE api_key_id = api_keys.id
                               AND month = DATE_TRUNC('month', CURRENT_DATE)::date), 0) AS used_micro_cents
            FROM api_keys WHERE team_id = ? AND is_active = true ORDER BY id
            """,
            (rs, n) -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("id", rs.getInt("id"));
                m.put("key_value", rs.getString("key_value"));
                m.put("name", rs.getString("name"));
                m.put("key_type", rs.getString("key_type"));
                m.put("user_id", rs.getObject("user_id"));
                m.put("environment", rs.getString("environment"));
                m.put("log", rs.getString("log"));
                m.put("settings", parseJson(rs.getString("settings_text")));
                m.put("default_priority", rs.getInt("default_priority"));
                m.put("is_active", rs.getBoolean("is_active"));
                m.put("use_custom_permissions", rs.getBoolean("use_custom_permissions"));
                m.put("used_micro_cents", rs.getLong("used_micro_cents"));
                return m;
            }, teamId);
    }

    public Optional<Map<String, Object>> getKeyById(int keyId) {
        List<Map<String, Object>> rows = jdbcTemplate.query("""
            SELECT id, key_value, name, key_type, team_id, user_id, environment,
                   default_priority, is_active, settings::text AS settings_text,
                   use_custom_permissions
            FROM api_keys WHERE id = ?
            """,
            (rs, n) -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("id", rs.getInt("id"));
                m.put("key_value", rs.getString("key_value"));
                m.put("name", rs.getString("name"));
                m.put("key_type", rs.getString("key_type"));
                m.put("team_id", rs.getObject("team_id"));
                m.put("user_id", rs.getObject("user_id"));
                m.put("environment", rs.getString("environment"));
                m.put("default_priority", rs.getInt("default_priority"));
                m.put("is_active", rs.getBoolean("is_active"));
                m.put("settings", parseJson(rs.getString("settings_text")));
                m.put("use_custom_permissions", rs.getBoolean("use_custom_permissions"));
                return m;
            }, keyId);
        return rows.isEmpty() ? Optional.empty() : Optional.of(rows.get(0));
    }

    public boolean isTeamOwner(int teamId, int userId) {
        Integer count = jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM team_members WHERE team_id=? AND user_id=? AND is_owner=true",
            Integer.class, teamId, userId);
        return count != null && count > 0;
    }

    public boolean duplicateAppKeyExists(int teamId, String environment) {
        Integer count = jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM api_keys WHERE team_id=? AND key_type='application' AND environment=? AND is_active=true",
            Integer.class, teamId, environment);
        return count != null && count > 0;
    }

    @Transactional
    public Map<String, Object> createAppKey(int teamId, CreateAppKeyRequest req) {
        String keyType = req.keyType() != null ? req.keyType() : "application";
        String environment = req.environment() != null ? req.environment() : "-";
        String log = req.log() != null ? req.log() : "BILLING";
        int defaultPriority = req.defaultPriority() != null ? req.defaultPriority() : 0;
        boolean useCustomPermissions = Boolean.TRUE.equals(req.useCustomPermissions());
        String settingsJson = req.settings() != null ? toJson(req.settings()) : null;

        String keyValue = generateKey(teamId, keyType, environment);
        Map<String, Object> row = jdbcTemplate.queryForMap("""
            INSERT INTO api_keys (key_value, name, key_type, team_id, user_id,
                environment, log, settings, default_priority, is_active, use_custom_permissions)
            VALUES (?, ?, CAST(? AS api_key_type_enum), ?, NULL,
                ?, CAST(? AS logging_enum), CAST(? AS jsonb), ?, true, ?)
            RETURNING id, key_value
            """,
            keyValue, req.name(), keyType, teamId,
            environment, log, settingsJson, defaultPriority, useCustomPermissions);

        return Map.of("result", "Application Key created",
                      "id", row.get("id"),
                      "api_key", row.get("key_value"));
    }

    public Map<String, Object> setLog(int keyId, String level) {
        if (!"BILLING".equals(level) && !"FULL".equals(level)) {
            throw new IllegalArgumentException("set_log must be BILLING or FULL");
        }
        int updated = jdbcTemplate.update(
            "UPDATE api_keys SET log = ?::logging_enum WHERE id = ?", level, keyId);
        if (updated == 0) {
            throw new IllegalArgumentException("API key not found: " + keyId);
        }
        return Map.of("result", "Updated log level to " + level);
    }

    @Transactional
    public void deactivateKey(int keyId) {
        jdbcTemplate.update("UPDATE api_keys SET is_active = false WHERE id = ?", keyId);
    }

    @Transactional
    public Map<String, Object> updateKey(int keyId, UpdateApiKeyRequest req) {
        String currentJson = jdbcTemplate.queryForObject(
            "SELECT settings::text FROM api_keys WHERE id = ?", String.class, keyId);
        Map<String, Object> settings = parseJsonToMap(currentJson);

        applyLimit(settings, "budget_limit_micro_cents", req.budgetLimitMicroCents());
        applyLimit(settings, "cloud_rpm_limit", req.cloudRpmLimit() != null ? req.cloudRpmLimit().longValue() : null);
        applyLimit(settings, "cloud_tpm_limit", req.cloudTpmLimit() != null ? req.cloudTpmLimit().longValue() : null);
        applyLimit(settings, "local_rpm_limit", req.localRpmLimit() != null ? req.localRpmLimit().longValue() : null);
        applyLimit(settings, "local_tpm_limit", req.localTpmLimit() != null ? req.localTpmLimit().longValue() : null);

        List<String> setClauses = new ArrayList<>(List.of("settings = CAST(? AS jsonb)"));
        List<Object> params = new ArrayList<>(List.of(toJson(settings)));

        if (req.environment() != null) { setClauses.add("environment = ?"); params.add(req.environment()); }
        if (req.defaultPriority() != null) { setClauses.add("default_priority = ?"); params.add(req.defaultPriority()); }
        if (req.log() != null) { setClauses.add("log = CAST(? AS logging_enum)"); params.add(req.log()); }
        if (req.useCustomPermissions() != null) { setClauses.add("use_custom_permissions = ?"); params.add(req.useCustomPermissions()); }

        params.add(keyId);
        jdbcTemplate.update(
            "UPDATE api_keys SET " + String.join(", ", setClauses) + " WHERE id = ?",
            params.toArray());

        return Map.of("result", "API Key updated successfully");
    }

    private String generateKey(int teamId, String keyType, String environment) {
        List<String> parts = new ArrayList<>();
        try {
            String teamName = jdbcTemplate.queryForObject("SELECT name FROM teams WHERE id=?", String.class, teamId);
            if (teamName != null) parts.add(teamName.toLowerCase());
        } catch (Exception ignored) {}
        if (parts.isEmpty()) parts.add("noteam");

        if ("application".equals(keyType) && environment != null && !environment.isBlank() && !"-".equals(environment)) {
            parts.add(environment.toLowerCase());
        }

        String label = String.join("-", parts)
            .replaceAll("[^a-z0-9\\-]", "-")
            .replaceAll("\\-+", "-")
            .replaceAll("^\\-|\\-$", "");
        if (label.length() > 35) label = label.substring(0, 35);

        byte[] bytes = new byte[96];
        SECURE_RANDOM.nextBytes(bytes);
        String token = java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        return "lg-" + label + "-" + token;
    }

    private void applyLimit(Map<String, Object> settings, String key, Long value) {
        if (value == null) return;
        if (value == -1L) settings.remove(key);
        else settings.put(key, value);
    }

    private Map<String, Object> parseJsonToMap(String json) {
        if (json == null || json.isBlank()) return new HashMap<>();
        try { return OBJECT_MAPPER.readValue(json, MAP_TYPE); }
        catch (Exception e) { return new HashMap<>(); }
    }

    private Object parseJson(String json) {
        if (json == null) return null;
        try { return OBJECT_MAPPER.readValue(json, Object.class); }
        catch (Exception e) { return json; }
    }

    private String toJson(Object obj) {
        if (obj == null) return null;
        try { return OBJECT_MAPPER.writeValueAsString(obj); }
        catch (Exception e) { return "{}"; }
    }
}
