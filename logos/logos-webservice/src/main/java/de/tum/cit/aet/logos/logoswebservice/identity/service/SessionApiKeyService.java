package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.audit.AuditLogService;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberId;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

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
 *
 * <p>Minting holds the owner's user row, the owner's membership row and the
 * parent key row while it re-checks authorization. An account deactivation or
 * a team leave that commits before the locks is seen by the re-checks, and
 * one in flight blocks until this transaction commits, so its key sweep
 * switches the child off with the rest. Without the locks, a sweep could
 * commit around a concurrent mint and leave an active key behind — the
 * gateway honours {@code is_active} alone and the orphan janitor only reaps
 * keys of terminal sessions, so nothing afterwards would take it away.
 */
@Service
public class SessionApiKeyService {

    private final ApiKeyRepository apiKeyRepository;
    private final TeamMemberRepository teamMemberRepository;
    private final UserRepository userRepository;
    private final NamedParameterJdbcTemplate jdbc;
    private final AuditLogService auditLog;

    public SessionApiKeyService(ApiKeyRepository apiKeyRepository,
                                TeamMemberRepository teamMemberRepository,
                                UserRepository userRepository,
                                NamedParameterJdbcTemplate jdbc,
                                AuditLogService auditLog) {
        this.apiKeyRepository = apiKeyRepository;
        this.teamMemberRepository = teamMemberRepository;
        this.userRepository = userRepository;
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
        if (parent.getParentApiKeyId() != null) {
            throw new IllegalArgumentException("a minted session key cannot mint further keys");
        }

        // Serialize with the deactivation paths, taking the same rows in the
        // same order they do: deactivateUser locks the owner's user row
        // before it sweeps the owner's keys, leave locks the owner's
        // membership row before it sweeps the team's, and both deactivate the
        // parent key this mint copies. A deactivation that committed before
        // the locks is visible to the re-checks below; one in flight blocks
        // until this transaction commits and then enumerates the child
        // minted here in its sweep.
        User owner = parent.getUserId() == null ? null : userRepository
            .findByIdForUpdate(parent.getUserId())
            .orElseThrow(() -> new IllegalArgumentException("parent API key's owner no longer exists"));
        boolean stillMember = owner == null || parent.getTeamId() == null
            || teamMemberRepository.findByIdForUpdate(
                new TeamMemberId(parent.getUserId(), parent.getTeamId())).isPresent();
        // Scalar on purpose: the parent entity above was read before the
        // locks, and an entity read now would hand back that cached copy
        // instead of the value a deactivation committed in the meantime.
        Boolean parentActive = jdbc.queryForObject("""
            SELECT is_active FROM api_keys WHERE id = :id FOR UPDATE
            """, new MapSqlParameterSource().addValue("id", parent.getId()), Boolean.class);

        if (!Boolean.TRUE.equals(parentActive)) {
            throw new IllegalArgumentException("parent API key is inactive");
        }
        if (owner != null && !owner.isActive()) {
            throw new IllegalArgumentException("parent API key's owner is deactivated");
        }
        if (!stillMember) {
            throw new IllegalArgumentException("parent API key's owner is no longer a member of the key's team");
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
