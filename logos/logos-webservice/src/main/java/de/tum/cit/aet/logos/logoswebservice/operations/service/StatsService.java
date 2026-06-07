package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.util.Map;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class StatsService {

    private final JdbcTemplate jdbcTemplate;

    public StatsService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Map<String, Object> generalStats() {
        long models = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM models", Long.class);
        long apiKeys = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM api_keys WHERE is_active = true", Long.class);
        long requests = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM log_entry", Long.class);
        return Map.of("models", models, "api_keys", apiKeys, "requests", requests);
    }

    public Map<String, Object> generalModelStats() {
        long count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM models", Long.class);
        return Map.of("totalModels", count);
    }

    public Map<String, Object> generalProviderStats() {
        long count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM providers", Long.class);
        return Map.of("totalProviders", count);
    }
}
