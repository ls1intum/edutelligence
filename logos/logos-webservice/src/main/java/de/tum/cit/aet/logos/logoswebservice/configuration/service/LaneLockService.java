package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.audit.AuditLogService;
import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

/**
 * Worker lanes an administrator has locked warm ({@code lane_locks}).
 *
 * <p>This service only writes the table. The capacity planner in
 * logos-orchestrator reads it every cycle and keeps a locked lane awake —
 * never idle-sleeps, drains or unloads it, and wakes it when it finds it
 * asleep — so no call to the orchestrator is needed here.
 *
 * <p>Locking and unlocking are idempotent: locking a locked lane refreshes
 * the model name and keeps the original lock, unlocking an unlocked lane is a
 * no-op. Both are recorded in the audit trail.
 */
@Service
public class LaneLockService {

    private final NamedParameterJdbcTemplate jdbc;
    private final UserRepository userRepository;
    private final AuditLogService auditLog;

    public LaneLockService(NamedParameterJdbcTemplate jdbc, UserRepository userRepository,
                           AuditLogService auditLog) {
        this.jdbc = jdbc;
        this.userRepository = userRepository;
        this.auditLog = auditLog;
    }

    /** All locks, oldest first. */
    public List<Map<String, Object>> listLocks() {
        return jdbc.queryForList("""
            SELECT provider_id, lane_id, model_name, locked_by, locked_at
            FROM lane_locks
            ORDER BY locked_at, provider_id, lane_id
            """, new MapSqlParameterSource());
    }

    /**
     * Locks a lane warm. Returns the stored lock.
     *
     * <p>The transition is read from the writes themselves, not from a read
     * before them: the insert reports whether it created the lock, and an
     * existing lock is row-locked before it is changed. Two concurrent first
     * locks therefore record one {@code lane.locked} entry — the losing insert
     * waits for the winner, then finds the lock and changes nothing.
     */
    @Transactional
    public Map<String, Object> lock(AuthContext actor, int providerId, String laneId, String modelName) {
        MapSqlParameterSource params = new MapSqlParameterSource()
            .addValue("providerId", providerId)
            .addValue("laneId", laneId)
            .addValue("modelName", blankToNull(modelName))
            .addValue("lockedBy", actorName(actor));
        Map<String, Object> before = null;
        Map<String, Object> after = null;
        // A concurrent unlock can delete the row between the insert that saw
        // it and the locking read; the insert is then simply tried again.
        while (after == null) {
            List<Map<String, Object>> inserted = jdbc.queryForList("""
                INSERT INTO lane_locks (provider_id, lane_id, model_name, locked_by)
                VALUES (:providerId, :laneId, :modelName, :lockedBy)
                ON CONFLICT (provider_id, lane_id) DO NOTHING
                RETURNING provider_id, lane_id, model_name, locked_by, locked_at
                """, params);
            if (!inserted.isEmpty()) {
                before = null;
                after = inserted.get(0);
                break;
            }
            List<Map<String, Object>> existing = jdbc.queryForList("""
                SELECT provider_id, lane_id, model_name, locked_by, locked_at
                FROM lane_locks WHERE provider_id = :providerId AND lane_id = :laneId
                FOR UPDATE
                """, params);
            if (existing.isEmpty()) {
                continue;
            }
            before = existing.get(0);
            after = jdbc.queryForList("""
                UPDATE lane_locks
                SET model_name = COALESCE(CAST(:modelName AS TEXT), model_name)
                WHERE provider_id = :providerId AND lane_id = :laneId
                RETURNING provider_id, lane_id, model_name, locked_by, locked_at
                """, params).get(0);
        }
        // record() drops a transition whose two states are equal, so a repeat
        // lock that changes nothing leaves no entry.
        auditLog.record("lane.locked", "lane", providerId + "/" + laneId, null,
            auditState(before), auditState(after));
        return after;
    }

    /**
     * Releases a lane lock. Returns whether a lock was removed. Only the call
     * whose delete removed the row records {@code lane.unlocked}.
     */
    @Transactional
    public boolean unlock(int providerId, String laneId) {
        List<Map<String, Object>> deleted = jdbc.queryForList("""
            DELETE FROM lane_locks WHERE provider_id = :providerId AND lane_id = :laneId
            RETURNING provider_id, lane_id, model_name, locked_by, locked_at
            """, new MapSqlParameterSource()
                .addValue("providerId", providerId)
                .addValue("laneId", laneId));
        if (deleted.isEmpty()) {
            return false;
        }
        auditLog.record("lane.unlocked", "lane", providerId + "/" + laneId, null,
            auditState(deleted.get(0)), Map.of());
        return true;
    }

    /** What the audit trail keeps of a lock: whether it is held, and for which model. */
    private static Map<String, Object> auditState(Map<String, Object> lock) {
        if (lock == null) {
            return Map.of();
        }
        Map<String, Object> state = new LinkedHashMap<>();
        state.put("locked", true);
        state.put("model_name", lock.get("model_name"));
        return state;
    }

    private String actorName(AuthContext actor) {
        if (actor == null || actor.userId() == null) {
            return null;
        }
        return userRepository.findById(actor.userId())
            .map(u -> u.getUsername() != null ? u.getUsername() : u.getEmail())
            .orElse(null);
    }

    private static String blankToNull(String s) {
        return s == null || s.isBlank() ? null : s.trim();
    }
}
