package de.tum.cit.aet.logos.logoswebservice.admin.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

@Service
public class ExportImportService {

    private static final List<String> TABLES = List.of(
        "users", "teams", "team_members", "api_keys", "providers", "models",
        "model_provider", "team_model_permissions", "api_key_model_permissions",
        "team_provider_permissions", "api_key_provider_permissions", "policies",
        "log_entry", "token_types", "usage_tokens", "token_prices", "jobs"
    );

    private static final List<String> SEQUENCE_TABLES = List.of(
        "users", "teams", "api_keys", "providers", "models",
        "model_provider", "policies", "log_entry",
        "token_types", "usage_tokens", "token_prices", "jobs"
    );

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;

    public ExportImportService(JdbcTemplate jdbc, ObjectMapper objectMapper) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> export() {
        Map<String, Object> data = new LinkedHashMap<>();
        for (String table : TABLES) {
            data.put(table, jdbc.queryForList("SELECT * FROM " + table));
        }
        return Map.of("result", data);
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
            jdbc.execute("TRUNCATE TABLE " + table + " CASCADE");
            if (rows != null && !rows.isEmpty()) {
                try {
                    String rowsJson = objectMapper.writeValueAsString(rows);
                    jdbc.update(
                        "INSERT INTO " + table
                        + " SELECT * FROM jsonb_populate_recordset(null::" + table + ", ?::jsonb)",
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
            jdbc.execute(
                "SELECT setval(pg_get_serial_sequence('" + table + "', 'id'), "
                + "COALESCE((SELECT MAX(id) FROM " + table + "), 0) + 1, false)"
            );
        }
    }
}
