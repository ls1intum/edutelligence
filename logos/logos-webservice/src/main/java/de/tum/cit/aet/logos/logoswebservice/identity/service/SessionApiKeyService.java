package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.audit.AuditLogService;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;

/**
 * Mints and revokes session API keys for the agent runner.
 *
 * <p>A minted key clones the standing agent key's team, settings, priority and
 * permissions. It cannot mint further keys ({@code parent_api_key_id} is set).
 * Lifetime equals the agent session: the runner revokes the key when the
 * session ends. Creation and {@code agent_sessions.session_api_key_id}
 * association commit in one transaction so an orphan janitor cannot revoke a
 * key that is about to be used. The key value is returned once to the caller
 * and never written to the audit log.
 */
@Service
public class SessionApiKeyService {

    private final ApiKeyRepository apiKeyRepository;
    private final NamedParameterJdbcTemplate jdbc;
    private final AuditLogService auditLog;

    public SessionApiKeyService(ApiKeyRepository apiKeyRepository,
                                NamedParameterJdbcTemplate jdbc,
                                AuditLogService auditLog) {
        this.apiKeyRepository = apiKeyRepository;
        this.jdbc = jdbc;
        this.auditLog = auditLog;
    }

    @Transactional
    public Map<String, Object> mint(String parentKeyValue, String name, Integer sessionId) {
        if (parentKeyValue == null || parentKeyValue.isBlank()) {
            throw new IllegalArgumentException("parent_key_value is required");
        }
        if (sessionId == null || sessionId <= 0) {
            throw new IllegalArgumentException("session_id is required");
        }

        ApiKey parent = apiKeyRepository.findByKeyValue(parentKeyValue)
            .orElseThrow(() -> new IllegalArgumentException("parent API key not found"));
        if (!Boolean.TRUE.equals(parent.getIsActive())) {
            throw new IllegalArgumentException("parent API key is inactive");
        }
        if (parent.getParentApiKeyId() != null) {
            throw new IllegalArgumentException("a minted session key cannot mint further keys");
        }

        String keyName = (name == null || name.isBlank())
            ? "agent-session-" + sessionId
            : name.trim();

        ApiKey child = new ApiKey();
        child.setKeyValue("lg-session-" + ApiKeyFactory.generateToken());
        child.setName(keyName);
        child.setKeyType(parent.getKeyType());
        child.setTeamId(parent.getTeamId());
        child.setUserId(parent.getUserId());
        child.setEnvironment(parent.getEnvironment());
        child.setLog(parent.getLog());
        child.setSettings(parent.getSettings() == null ? "{}" : parent.getSettings());
        child.setDefaultPriority(parent.getDefaultPriority() == null ? 0 : parent.getDefaultPriority());
        child.setIsActive(true);
        child.setUseCustomPermissions(Boolean.TRUE.equals(parent.getUseCustomPermissions()));
        child.setParentApiKeyId(parent.getId());
        // Flush before the association UPDATE so the FK target is visible to JDBC
        // in this same transaction; a failed link rolls the key back with it.
        child = apiKeyRepository.saveAndFlush(child);

        if (Boolean.TRUE.equals(child.getUseCustomPermissions())) {
            copyPermissions(parent.getId(), child.getId());
        }

        int linked = jdbc.update("""
            UPDATE agent_sessions
               SET session_api_key_id = :keyId
             WHERE id = :sessionId
               AND status IN ('starting', 'running', 'paused', 'finalizing')
               AND (session_api_key_id IS NULL OR session_api_key_id = :keyId)
            """, new MapSqlParameterSource()
                .addValue("keyId", child.getId())
                .addValue("sessionId", sessionId));
        if (linked != 1) {
            throw new IllegalArgumentException(
                "agent session " + sessionId + " is missing, terminal, or already has a session key");
        }

        Map<String, Object> after = new LinkedHashMap<>();
        after.put("parent_api_key_id", parent.getId());
        after.put("name", keyName);
        after.put("session_id", sessionId);
        after.put("minted_by", "agent");
        auditLog.record("api_key.agent_minted", "api_key", child.getId(), child.getTeamId(), Map.of(), after);

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("id", child.getId());
        response.put("key_value", child.getKeyValue());
        response.put("parent_api_key_id", parent.getId());
        return response;
    }

    @Transactional
    public void revoke(int keyId) {
        ApiKey key = apiKeyRepository.findById(keyId)
            .orElseThrow(() -> new IllegalArgumentException("API key not found: " + keyId));
        // Only minted session keys may be revoked here: a standing key must
        // never be switched off through the internal runner endpoint.
        if (key.getParentApiKeyId() == null) {
            throw new IllegalArgumentException("API key not found: " + keyId);
        }
        if (!Boolean.TRUE.equals(key.getIsActive())) {
            return;
        }
        key.setIsActive(false);
        apiKeyRepository.save(key);
        auditLog.record(
            "api_key.agent_revoked",
            "api_key",
            keyId,
            key.getTeamId(),
            Map.of("is_active", true),
            Map.of("is_active", false, "parent_api_key_id", key.getParentApiKeyId()));
    }

    private void copyPermissions(int parentId, int childId) {
        jdbc.update("""
            INSERT INTO api_key_model_permissions (api_key_id, model_id)
            SELECT :childId, model_id FROM api_key_model_permissions WHERE api_key_id = :parentId
            ON CONFLICT DO NOTHING
            """, new MapSqlParameterSource()
                .addValue("childId", childId)
                .addValue("parentId", parentId));
        jdbc.update("""
            INSERT INTO api_key_provider_permissions (api_key_id, provider_id)
            SELECT :childId, provider_id FROM api_key_provider_permissions WHERE api_key_id = :parentId
            ON CONFLICT DO NOTHING
            """, new MapSqlParameterSource()
                .addValue("childId", childId)
                .addValue("parentId", parentId));
    }
}
