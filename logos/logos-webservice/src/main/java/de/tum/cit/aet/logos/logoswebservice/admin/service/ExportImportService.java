package de.tum.cit.aet.logos.logoswebservice.admin.service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

@Service
public class ExportImportService {

    private static final List<String> TABLES = List.of(
        "users", "teams", "team_repositories", "team_repository_credentials",
        "team_members", "api_keys", "providers", "models",
        "model_provider", "team_model_permissions", "api_key_model_permissions",
        "team_provider_permissions", "api_key_provider_permissions", "policies",
        "ai_workflow_analyses", "ai_workflows", "ai_llm_call_recommendations",
        "log_entry", "token_types", "usage_tokens", "token_prices", "jobs"
    );
    private static final Set<String> TABLE_WHITELIST = Set.copyOf(TABLES);

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
        for (String table : TABLES) {
            if (!jsonData.containsKey(table)) {
                throw new IllegalArgumentException("Missing table in json: " + table);
            }
        }
        for (String table : TABLES) {
            List<?> rows = (List<?>) jsonData.get(table);
            jdbc.execute("TRUNCATE TABLE " + safeTable(table) + " CASCADE");
            if (rows != null && !rows.isEmpty()) {
                try {
                    String rowsJson = objectMapper.writeValueAsString(rows);
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
        resetSequences();
        return Map.of("result", "Import successful");
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
