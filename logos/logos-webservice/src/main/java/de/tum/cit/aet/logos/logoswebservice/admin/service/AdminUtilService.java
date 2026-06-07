package de.tum.cit.aet.logos.logoswebservice.admin.service;

import java.util.Map;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class AdminUtilService {

    private final JdbcTemplate jdbc;

    public AdminUtilService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Map<String, Object> setLog(int keyId, String level) {
        if (!"BILLING".equals(level) && !"FULL".equals(level)) {
            throw new IllegalArgumentException("set_log must be BILLING or FULL");
        }
        int updated = jdbc.update(
            "UPDATE api_keys SET log = ?::logging_enum WHERE id = ?", level, keyId);
        if (updated == 0) {
            throw new IllegalArgumentException("API key not found: " + keyId);
        }
        return Map.of("result", "Updated log level to " + level);
    }
}