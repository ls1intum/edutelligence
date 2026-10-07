package de.tum.cit.aet.logos.logoswebservice.audit;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.context.request.RequestContextHolder;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

/**
 * Append-only record of who changed which budget or logging/privacy setting.
 *
 * <p>The actor is the caller of the current HTTP request ({@code authContext}
 * request attribute), so a service does not have to be handed it and a new
 * write path cannot forget it. Outside a request (a sync job, a test) the
 * actor is empty and the row says so.
 *
 * <p>{@link #record} joins the caller's transaction: the change and its audit
 * row commit or roll back together. Only fields that changed are stored, and
 * nothing here may be given a secret.
 */
@Service
public class AuditLogService {

    private static final Logger log = LoggerFactory.getLogger(AuditLogService.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();
    public static final int MAX_PAGE = 200;

    private final NamedParameterJdbcTemplate jdbc;
    private final UserRepository userRepository;

    public AuditLogService(NamedParameterJdbcTemplate jdbc, UserRepository userRepository) {
        this.jdbc = jdbc;
        this.userRepository = userRepository;
    }

    /**
     * Records one change. A no-op when {@code before} and {@code after} are
     * equal, so saving a form without touching it leaves no trace.
     *
     * @param action     dotted verb, e.g. {@code team.provider_budget_set}
     * @param targetType what was changed: team, api_key, provider
     * @param targetId   id of that thing
     * @param teamId     owning team when there is one; lets a team owner read its own trail
     */
    public void record(String action, String targetType, Object targetId, Integer teamId,
                       Map<String, Object> before, Map<String, Object> after) {
        Map<String, Object> from = before == null ? Map.of() : before;
        Map<String, Object> to = after == null ? Map.of() : after;
        Map<String, Object> changedFrom = new LinkedHashMap<>();
        Map<String, Object> changedTo = new LinkedHashMap<>();
        for (String key : union(from, to)) {
            Object was = normalize(from.get(key));
            Object is = normalize(to.get(key));
            if (!Objects.equals(was, is)) {
                changedFrom.put(key, was);
                changedTo.put(key, is);
            }
        }
        if (changedTo.isEmpty()) {
            return;
        }

        Integer actorId = null;
        String actorRole = null;
        String actorName = null;
        AuthContext actor = currentActor();
        if (actor != null) {
            actorId = actor.userId();
            actorRole = actor.role();
            if (actorId != null) {
                actorName = userRepository.findById(actorId).map(User::getUsername).orElse(null);
            }
        }

        jdbc.update("""
            INSERT INTO audit_log
                (actor_user_id, actor_username, actor_role, action, target_type, target_id,
                 team_id, before_state, after_state)
            VALUES
                (:actorId, :actorName, :actorRole, :action, :targetType, :targetId,
                 :teamId, CAST(:before AS jsonb), CAST(:after AS jsonb))
            """, new MapSqlParameterSource()
                .addValue("actorId", actorId)
                .addValue("actorName", actorName)
                .addValue("actorRole", actorRole)
                .addValue("action", action)
                .addValue("targetType", targetType)
                .addValue("targetId", targetId == null ? null : String.valueOf(targetId))
                .addValue("teamId", teamId)
                .addValue("before", json(changedFrom))
                .addValue("after", json(changedTo)));
        log.info("audit: {} {} {} by {}", action, targetType, targetId, actorName != null ? actorName : actorId);
    }

    /** Newest first. {@code teamId} null reads everything; {@code beforeId} pages. */
    public List<Map<String, Object>> list(Integer teamId, Long beforeId, int limit) {
        int size = Math.max(1, Math.min(limit, MAX_PAGE));
        return jdbc.queryForList("""
            SELECT id, occurred_at, actor_user_id, actor_username, actor_role, action,
                   target_type, target_id, team_id,
                   CAST(before_state AS text) AS before_state, CAST(after_state AS text) AS after_state
            FROM audit_log
            WHERE (CAST(:teamId AS integer) IS NULL OR team_id = CAST(:teamId AS integer))
              AND (CAST(:beforeId AS bigint) IS NULL OR id < CAST(:beforeId AS bigint))
            ORDER BY id DESC
            LIMIT :size
            """, new MapSqlParameterSource()
                .addValue("teamId", teamId)
                .addValue("beforeId", beforeId)
                .addValue("size", size))
            .stream()
            .map(row -> {
                Map<String, Object> m = new LinkedHashMap<>(row);
                m.put("before_state", parse(row.get("before_state")));
                m.put("after_state", parse(row.get("after_state")));
                return m;
            })
            .toList();
    }

    /**
     * Jackson reads a small JSON integer as Integer while a limit written from a
     * request is a Long; both mean the same number, so they must compare equal.
     */
    private static Object normalize(Object value) {
        return value instanceof Integer || value instanceof Short || value instanceof Byte
            ? Long.valueOf(((Number) value).longValue())
            : value;
    }

    private static java.util.Set<String> union(Map<String, Object> a, Map<String, Object> b) {
        java.util.Set<String> keys = new java.util.LinkedHashSet<>(a.keySet());
        keys.addAll(b.keySet());
        return keys;
    }

    private static AuthContext currentActor() {
        RequestAttributes attrs = RequestContextHolder.getRequestAttributes();
        if (attrs == null) {
            return null;
        }
        Object ctx = attrs.getAttribute("authContext", RequestAttributes.SCOPE_REQUEST);
        return ctx instanceof AuthContext a ? a : null;
    }

    private static String json(Map<String, Object> value) {
        try {
            return MAPPER.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            // The change itself must not fail because its description did not
            // serialise; the row still says what was changed and by whom.
            return "{\"unserialisable\":true}";
        }
    }

    private static Object parse(Object text) {
        if (text == null) {
            return null;
        }
        try {
            return MAPPER.readValue(text.toString(), Object.class);
        } catch (JsonProcessingException e) {
            return text;
        }
    }
}
