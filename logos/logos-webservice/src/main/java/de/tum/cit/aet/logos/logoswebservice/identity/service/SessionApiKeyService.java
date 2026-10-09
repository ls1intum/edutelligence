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
 * Mints and revokes short-lived session API keys for the agent runner.
 *
 * <p>A minted key clones the standing agent key's team, settings, priority and
 * permissions. It cannot mint further keys ({@code parent_api_key_id} is set).
 * The key value is returned once to the caller and never written to the audit
 * log.
 */
@Service
public class SessionApiKeyService {

    /** Hard ceiling on a session key's lifetime (24 hours). */
    public static final int MAX_TTL_SECONDS = 86_400;

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
    public Map<String, Object> mint(String parentKeyValue, int ttlSeconds, String name) {
        if (parentKeyValue == null || parentKeyValue.isBlank()) {
            throw new IllegalArgumentException("parent_key_value is required");
        }
        if (ttlSeconds <= 0) {
            throw new IllegalArgumentException("ttl_seconds must be positive");
        }
        if (ttlSeconds > MAX_TTL_SECONDS) {
            throw new IllegalArgumentException("ttl_seconds exceeds the " + MAX_TTL_SECONDS + "s cap");
        }

        ApiKey parent = apiKeyRepository.findByKeyValue(parentKeyValue)
            .orElseThrow(() -> new IllegalArgumentException("parent API key not found"));
        if (!Boolean.TRUE.equals(parent.getIsActive())) {
            throw new IllegalArgumentException("parent API key is inactive");
        }
        if (parent.getExpiresAt() != null && !parent.getExpiresAt().isAfter(Instant.now())) {
            throw new IllegalArgumentException("parent API key is expired");
        }
        if (parent.getParentApiKeyId() != null) {
            throw new IllegalArgumentException("a minted session key cannot mint further keys");
        }

        Instant expiresAt = Instant.now().plusSeconds(ttlSeconds);
        String keyName = (name == null || name.isBlank())
            ? "agent-session-" + parent.getId() + "-" + Instant.now().getEpochSecond()
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
        child.setExpiresAt(expiresAt);
        child.setParentApiKeyId(parent.getId());
        child = apiKeyRepository.save(child);

        if (Boolean.TRUE.equals(child.getUseCustomPermissions())) {
            copyPermissions(parent.getId(), child.getId());
        }

        Map<String, Object> after = new LinkedHashMap<>();
        after.put("parent_api_key_id", parent.getId());
        after.put("expires_at", expiresAt.toString());
        after.put("name", keyName);
        after.put("minted_by", "agent");
        auditLog.record("api_key.agent_minted", "api_key", child.getId(), child.getTeamId(), Map.of(), after);

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("id", child.getId());
        response.put("key_value", child.getKeyValue());
        response.put("expires_at", expiresAt.toString());
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
