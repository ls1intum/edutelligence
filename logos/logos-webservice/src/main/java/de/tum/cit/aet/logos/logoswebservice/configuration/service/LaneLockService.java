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
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorNotificationService;

/**
 * Worker lanes an administrator has locked warm ({@code lane_locks}).
 *
 * <p>This service writes the table and, once a change is committed, pushes it
 * to logos-orchestrator. The capacity planner serves the locks from memory
 * (it re-reads the table only in the background, to catch a lost push) and
 * keeps a locked lane awake — never idle-sleeps, drains or unloads it, and
 * wakes it when it finds it asleep.
 *
 * <p>Locking and unlocking are idempotent: locking a locked lane refreshes
 * the model name and keeps the original lock, unlocking an unlocked lane is a
 * no-op. Both are recorded in the audit trail.
 *
 * <p>The lane id {@value #WORKER_LANE_ID} locks a whole worker: the planner
 * then neither loads, wakes, sleeps nor unloads anything there on its own.
 * For a locked lane, and every lane of a locked worker, the planner records
 * the lane in {@code restore_lanes} and puts it back after a worker restart;
 * a new lock starts with no record.
 *
 * <p>Every change draws a new revision from {@code lane_lock_revision_seq}
 * and is pushed with it, because the pushes are asynchronous and can arrive
 * out of order; the planner ignores a change older than the one it holds.
 * An unlock therefore keeps the row ({@code locked = FALSE}) with its
 * revision instead of deleting it.
 */
@Service
public class LaneLockService {

    /** The lane id of a lock on a whole worker. No worker lane has this id. */
    public static final String WORKER_LANE_ID = "*";

    private final NamedParameterJdbcTemplate jdbc;
    private final UserRepository userRepository;
    private final AuditLogService auditLog;
    private final OrchestratorNotificationService orchestratorNotification;

    public LaneLockService(NamedParameterJdbcTemplate jdbc, UserRepository userRepository,
                           AuditLogService auditLog, OrchestratorNotificationService orchestratorNotification) {
        this.jdbc = jdbc;
        this.userRepository = userRepository;
        this.auditLog = auditLog;
        this.orchestratorNotification = orchestratorNotification;
    }

    /** All locks, oldest first. */
    public List<Map<String, Object>> listLocks() {
        return jdbc.queryForList("""
            SELECT provider_id, lane_id, model_name, locked_by, locked_at
            FROM lane_locks
            WHERE locked
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
        Map<String, Object> after;
        List<Map<String, Object>> inserted = jdbc.queryForList("""
            INSERT INTO lane_locks (provider_id, lane_id, model_name, locked_by, locked, revision)
            VALUES (:providerId, :laneId, :modelName, :lockedBy, TRUE, nextval('lane_lock_revision_seq'))
            ON CONFLICT (provider_id, lane_id) DO NOTHING
            RETURNING provider_id, lane_id, model_name, locked_by, locked_at, revision,
                CAST(restore_lanes AS TEXT) AS restore_lanes
            """, params);
        if (!inserted.isEmpty()) {
            after = inserted.get(0);
        } else {
            // The row exists (rows are never deleted, an unlock only clears
            // locked): lock it, then read its previous state.
            Map<String, Object> existing = jdbc.queryForList("""
                SELECT provider_id, lane_id, model_name, locked_by, locked_at, locked
                FROM lane_locks WHERE provider_id = :providerId AND lane_id = :laneId
                FOR UPDATE
                """, params).get(0);
            if (Boolean.TRUE.equals(existing.get("locked"))) {
                before = existing;
            }
            after = jdbc.queryForList("""
                UPDATE lane_locks
                SET model_name = CASE WHEN locked THEN COALESCE(CAST(:modelName AS TEXT), model_name)
                                      ELSE CAST(:modelName AS TEXT) END,
                    locked_by = CASE WHEN locked THEN locked_by ELSE CAST(:lockedBy AS TEXT) END,
                    locked_at = CASE WHEN locked THEN locked_at ELSE now() END,
                    restore_lanes = CASE WHEN locked THEN restore_lanes ELSE NULL END,
                    locked = TRUE,
                    revision = nextval('lane_lock_revision_seq')
                WHERE provider_id = :providerId AND lane_id = :laneId
                RETURNING provider_id, lane_id, model_name, locked_by, locked_at, revision,
                    CAST(restore_lanes AS TEXT) AS restore_lanes
                """, params).get(0);
        }
        // record() drops a transition whose two states are equal, so a repeat
        // lock that changes nothing leaves no entry.
        auditLog.record(auditAction(laneId, "locked"), auditTarget(laneId), auditId(providerId, laneId), null,
            auditState(before), auditState(after));
        orchestratorNotification.notifyLaneLock(providerId, laneId, true, revisionOf(after),
            (String) after.get("restore_lanes"));
        Map<String, Object> stored = new LinkedHashMap<>(after);
        stored.remove("revision");
        stored.remove("restore_lanes");
        return stored;
    }

    /**
     * Releases a lane lock. Returns whether a lock was released. Only the call
     * whose update cleared the lock records {@code lane.unlocked}.
     */
    @Transactional
    public boolean unlock(int providerId, String laneId) {
        List<Map<String, Object>> released = jdbc.queryForList("""
            UPDATE lane_locks
            SET locked = FALSE, revision = nextval('lane_lock_revision_seq')
            WHERE provider_id = :providerId AND lane_id = :laneId AND locked
            RETURNING provider_id, lane_id, model_name, locked_by, locked_at, revision
            """, new MapSqlParameterSource()
                .addValue("providerId", providerId)
                .addValue("laneId", laneId));
        if (released.isEmpty()) {
            return false;
        }
        auditLog.record(auditAction(laneId, "unlocked"), auditTarget(laneId), auditId(providerId, laneId), null,
            auditState(released.get(0)), Map.of());
        orchestratorNotification.notifyLaneLock(providerId, laneId, false, revisionOf(released.get(0)));
        return true;
    }

    private static String auditAction(String laneId, String change) {
        return auditTarget(laneId) + "." + change;
    }

    private static String auditTarget(String laneId) {
        return WORKER_LANE_ID.equals(laneId) ? "worker" : "lane";
    }

    private static String auditId(int providerId, String laneId) {
        return WORKER_LANE_ID.equals(laneId) ? String.valueOf(providerId) : providerId + "/" + laneId;
    }

    private static long revisionOf(Map<String, Object> row) {
        return ((Number) row.get("revision")).longValue();
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
