package de.tum.cit.aet.logos.logoswebservice.admin.service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.identity.ObjectivePriority;

@Service
public class ExportImportService {

    static final List<String> TABLES = List.of(
        "users", "teams", "team_repositories", "team_repository_credentials",
        "team_members", "api_keys", "providers", "models",
        "model_provider", "team_model_permissions", "api_key_model_permissions",
        "team_provider_permissions", "api_key_provider_permissions", "policies",
        "team_provider_budgets",
        "ai_workflow_analyses", "ai_workflows", "ai_llm_call_recommendations",
        "log_entry", "token_types", "usage_tokens", "token_prices", "jobs"
    );
    private static final Set<String> TABLE_WHITELIST = Set.copyOf(TABLES);

    /** Tables added after exports already existed; an export without one restores it empty. */
    private static final Set<String> OPTIONAL_TABLES = Set.of("team_provider_budgets");

    private static final List<String> SEQUENCE_TABLES = List.of(
        "users", "teams", "team_repositories", "api_keys", "providers", "models",
        "model_provider", "policies",
        "ai_workflow_analyses", "ai_workflows", "ai_llm_call_recommendations",
        "log_entry", "token_types", "usage_tokens", "token_prices", "jobs"
    );

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;

    public ExportImportService(JdbcTemplate jdbc, ObjectMapper objectMapper) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
    }

    private static String safeTable(String table) {
        if (!TABLE_WHITELIST.contains(table)) {
            throw new IllegalArgumentException("Unsafe table name: " + table);
        }
        return table;
    }

    public Map<String, Object> export() {
        Map<String, Object> data = new LinkedHashMap<>();
        for (String table : TABLES) {
            List<Map<String, Object>> rows = jdbc.queryForList("SELECT * FROM " + safeTable(table));
            data.put(table, decodeJsonbColumns(rows));
        }
        return Map.of("result", data);
    }

    /**
     * JDBC returns PostgreSQL {@code jsonb} as {@link PGobject}. Jackson would
     * otherwise serialize {@code type}/{@code value} metadata and import would
     * persist that object instead of the original array/document.
     */
    List<Map<String, Object>> decodeJsonbColumns(List<Map<String, Object>> rows) {
        List<Map<String, Object>> decoded = new ArrayList<>(rows.size());
        for (Map<String, Object> row : rows) {
            Map<String, Object> copy = new LinkedHashMap<>(row.size());
            for (Map.Entry<String, Object> entry : row.entrySet()) {
                copy.put(entry.getKey(), decodeJsonbValue(entry.getValue()));
            }
            decoded.add(copy);
        }
        return decoded;
    }

    /**
     * JDBC returns PostgreSQL jsonb as {@code org.postgresql.util.PGobject}.
     * Jackson would otherwise serialize {@code type}/{@code value} metadata and
     * import would persist that object instead of the original array/document.
     * Reflect over the driver type so compile does not depend on the runtime
     * JDBC jar being on the compile classpath.
     */
    private Object decodeJsonbValue(Object value) {
        if (value == null || !"org.postgresql.util.PGobject".equals(value.getClass().getName())) {
            return value;
        }
        try {
            String type = (String) value.getClass().getMethod("getType").invoke(value);
            if (type == null || (!type.equalsIgnoreCase("json") && !type.equalsIgnoreCase("jsonb"))) {
                return value;
            }
            String raw = (String) value.getClass().getMethod("getValue").invoke(value);
            if (raw == null || raw.isBlank()) {
                return null;
            }
            return objectMapper.readValue(raw, Object.class);
        } catch (ReflectiveOperationException | JsonProcessingException e) {
            throw new IllegalArgumentException("Failed to decode jsonb value: " + e.getMessage(), e);
        }
    }

    @Transactional
    public Map<String, Object> importData(Map<String, Object> jsonData) {
        requireTables(jsonData);
        // Snapshot (session_id → team_id + repo_slug) so linked analysis
        // sessions can be reattached after truncate replaces repository rows.
        List<Map<String, Object>> sessionLinks = jdbc.queryForList("""
            SELECT s.id AS session_id, tr.team_id, tr.repo_slug
              FROM agent_sessions s
              JOIN team_repositories tr ON tr.id = s.team_repository_id
            """);
        // Snapshot session → key VALUE (not id) so a running minted-key
        // session stays linked after api_keys is truncated and re-imported.
        // Matching by value prevents an imported row id from attaching a
        // session to a different credential.
        List<Map<String, Object>> sessionKeyLinks = jdbc.queryForList("""
            SELECT s.id AS session_id, k.key_value
              FROM agent_sessions s
              JOIN api_keys k ON k.id = s.session_api_key_id
            """);
        detachAgentSessionsFromRepositories();
        try {
            for (String table : TABLES) {
                List<?> rows = (List<?>) jsonData.getOrDefault(table, List.of());
                jdbc.execute("TRUNCATE TABLE " + safeTable(table) + " CASCADE");
                List<Map<String, Object>> normalized = normalizeImportRows(table, rows);
                if (!normalized.isEmpty()) {
                    try {
                        String rowsJson = objectMapper.writeValueAsString(normalized);
                        jdbc.update(
                            "INSERT INTO " + safeTable(table)
                            + " SELECT * FROM jsonb_populate_recordset(null::" + safeTable(table) + ", ?::jsonb)",
                            rowsJson
                        );
                    } catch (JsonProcessingException e) {
                        throw new IllegalArgumentException(
                            "Failed to serialize rows for table " + table + ": " + e.getMessage());
                    }
                }
            }
        } finally {
            restoreAgentSessionsRepositoryFk();
        }
        restoreAgentSessionRepositoryLinks(sessionLinks);
        restoreAgentSessionApiKeyLinks(sessionKeyLinks);
        sanitizeImportedAnalysisSessionLinks();
        resetSequences();
        return Map.of("result", "Import successful");
    }

    static void requireTables(Map<String, Object> jsonData) {
        for (String table : TABLES) {
            if (!jsonData.containsKey(table) && !OPTIONAL_TABLES.contains(table)) {
                throw new IllegalArgumentException("Missing table in json: " + table);
            }
        }
    }

    /**
     * Backfill NOT NULL JSONB columns added after older exports were taken.
     * {@code jsonb_populate_recordset} turns omitted keys into explicit NULL,
     * which rejects the column default — so pre-044 dumps must be normalized.
     */
    List<Map<String, Object>> normalizeImportRows(String table, List<?> rows) {
        if (rows == null || rows.isEmpty()) {
            return List.of();
        }
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (Object item : rows) {
            if (!(item instanceof Map<?, ?> raw)) {
                continue;
            }
            Map<String, Object> copy = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : raw.entrySet()) {
                if (entry.getKey() == null) {
                    continue;
                }
                copy.put(String.valueOf(entry.getKey()), entry.getValue());
            }
            if ("models".equals(table) && copy.get("profile_ratings") == null) {
                copy.put("profile_ratings", Map.of());
            }
            if ("ai_llm_call_recommendations".equals(table)) {
                // Dumps taken before the sla → slo column rename still carry the
                // old key names; jsonb_populate_recordset drops unknown keys,
                // which would fail the NOT NULL recommended_slo insert.
                if (copy.get("recommended_slo") == null && copy.get("recommended_sla") != null) {
                    copy.put("recommended_slo", copy.remove("recommended_sla"));
                }
                if (copy.get("confirmed_slo") == null && copy.get("confirmed_sla") != null) {
                    copy.put("confirmed_slo", copy.remove("confirmed_sla"));
                }
                for (String flag : List.of("model_set_by_owner", "review_carried_over")) {
                    if (copy.get(flag) == null) copy.put(flag, false);
                }
                if (copy.get("objective_priority") == null) {
                    Object slo = copy.get("recommended_slo");
                    copy.put(
                        "objective_priority",
                        ObjectivePriority.forSlo(slo == null ? null : String.valueOf(slo)));
                }
            }
            if ("ai_workflows".equals(table) && copy.get("diagram_set_by_owner") == null) {
                copy.put("diagram_set_by_owner", false);
            }
            out.add(copy);
        }
        if ("ai_workflow_analyses".equals(table)) {
            failOlderInFlightAnalyses(out);
        }
        return out;
    }

    /**
     * Exports from before the one-in-flight-per-repository index may hold
     * several queued/running analyses of one repository; the index would
     * reject them. Keep the newest per repository and mark the others failed,
     * as Liquibase 050 does for an upgraded database.
     */
    private static void failOlderInFlightAnalyses(List<Map<String, Object>> rows) {
        Map<Object, Map<String, Object>> newest = new HashMap<>();
        for (Map<String, Object> row : rows) {
            if (!isInFlight(row) || row.get("team_repository_id") == null) continue;
            newest.merge(row.get("team_repository_id"), row,
                (a, b) -> idOf(b) > idOf(a) ? b : a);
        }
        for (Map<String, Object> row : rows) {
            Object repo = row.get("team_repository_id");
            if (isInFlight(row) && repo != null && newest.get(repo) != row) {
                row.put("status", "failed");
                if (row.get("error") == null) row.put("error", "superseded by a newer queued analysis");
                if (row.get("finished_at") == null) row.put("finished_at", row.get("started_at"));
            }
        }
    }

    private static boolean isInFlight(Map<String, Object> row) {
        Object status = row.get("status");
        return "queued".equals(status) || "running".equals(status);
    }

    private static long idOf(Map<String, Object> row) {
        Object id = row.get("id");
        return id instanceof Number n ? n.longValue() : Long.parseLong(String.valueOf(id));
    }

    private void detachAgentSessionsFromRepositories() {
        // Drop FKs that would make TRUNCATE … CASCADE of exported tables
        // wipe preserved agent_sessions rows (repositories and session keys).
        jdbc.update("UPDATE agent_sessions SET team_repository_id = NULL "
            + "WHERE team_repository_id IS NOT NULL");
        jdbc.update("UPDATE agent_sessions SET session_api_key_id = NULL "
            + "WHERE session_api_key_id IS NOT NULL");
        jdbc.execute("ALTER TABLE agent_sessions DROP CONSTRAINT IF EXISTS "
            + "agent_sessions_team_repository_id_fkey");
        jdbc.execute("ALTER TABLE agent_sessions DROP CONSTRAINT IF EXISTS "
            + "agent_sessions_session_api_key_id_fkey");
    }

    private void restoreAgentSessionsRepositoryFk() {
        jdbc.execute("""
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conname = 'agent_sessions_team_repository_id_fkey'
              ) THEN
                ALTER TABLE agent_sessions
                  ADD CONSTRAINT agent_sessions_team_repository_id_fkey
                  FOREIGN KEY (team_repository_id)
                  REFERENCES team_repositories(id) ON DELETE SET NULL;
              END IF;
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conname = 'agent_sessions_session_api_key_id_fkey'
              ) THEN
                ALTER TABLE agent_sessions
                  ADD CONSTRAINT agent_sessions_session_api_key_id_fkey
                  FOREIGN KEY (session_api_key_id)
                  REFERENCES api_keys(id) ON DELETE SET NULL;
              END IF;
            END $$;
            """);
    }

    private void restoreAgentSessionRepositoryLinks(List<Map<String, Object>> sessionLinks) {
        for (Map<String, Object> link : sessionLinks) {
            Number sessionId = (Number) link.get("session_id");
            Number teamId = (Number) link.get("team_id");
            String repoSlug = (String) link.get("repo_slug");
            if (sessionId == null || teamId == null || repoSlug == null) {
                continue;
            }
            jdbc.update("""
                UPDATE agent_sessions s
                   SET team_repository_id = tr.id
                  FROM team_repositories tr
                 WHERE s.id = ?
                   AND tr.team_id = ?
                   AND tr.repo_slug = ?
                """, sessionId.intValue(), teamId.intValue(), repoSlug);
        }
    }

    private void restoreAgentSessionApiKeyLinks(List<Map<String, Object>> sessionKeyLinks) {
        for (Map<String, Object> link : sessionKeyLinks) {
            Number sessionId = (Number) link.get("session_id");
            String keyValue = (String) link.get("key_value");
            if (sessionId == null || keyValue == null || keyValue.isBlank()) {
                continue;
            }
            jdbc.update("""
                UPDATE agent_sessions s
                   SET session_api_key_id = k.id
                  FROM api_keys k
                 WHERE s.id = ?
                   AND k.key_value = ?
                """, sessionId.intValue(), keyValue);
        }
    }

    /**
     * Imported analyses may reuse {@code agent_session_id} values that still
     * belong to preserved local sessions for a different team/repository.
     * Clear those associations so a finishing local session cannot overwrite
     * another repository's imported analysis via session-id upsert.
     */
    void sanitizeImportedAnalysisSessionLinks() {
        jdbc.update("""
            UPDATE ai_workflow_analyses a
               SET agent_session_id = NULL,
                   status = CASE
                       WHEN a.status IN ('queued', 'running') THEN 'failed'
                       ELSE a.status
                   END,
                   error = CASE
                       WHEN a.status IN ('queued', 'running') THEN
                           'imported session association cleared: local session targets a different repository'
                       ELSE a.error
                   END,
                   finished_at = CASE
                       WHEN a.status IN ('queued', 'running') THEN CURRENT_TIMESTAMP
                       ELSE a.finished_at
                   END
             WHERE a.agent_session_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1
                     FROM agent_sessions s
                     JOIN team_repositories tr ON tr.id = s.team_repository_id
                    WHERE s.id = a.agent_session_id
                      AND s.team_repository_id = a.team_repository_id
                      AND tr.team_id = a.team_id
               )
            """);
    }

    private void resetSequences() {
        for (String table : SEQUENCE_TABLES) {
            String seqName = jdbc.queryForObject(
                "SELECT pg_get_serial_sequence(?, 'id')", String.class, table);
            if (seqName == null) continue;
            Long maxId = jdbc.queryForObject(
                "SELECT COALESCE(MAX(id), 0) FROM " + safeTable(table), Long.class);
            jdbc.queryForObject("SELECT setval(?, ?, false)", Long.class, seqName, maxId == null ? 1L : maxId + 1);
        }
    }
}
