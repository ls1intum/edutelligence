package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PolicyService {

    private final JdbcTemplate jdbcTemplate;

    public PolicyService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<Map<String, Object>> getPolicies(String keyValue) {
        boolean isAdmin = Boolean.TRUE.equals(jdbcTemplate.queryForObject("""
            SELECT COUNT(*) > 0 FROM api_keys ak
            JOIN users u ON ak.user_id = u.id
            WHERE ak.key_value = ? AND u.role = 'logos_admin' AND ak.is_active = true
            """, Boolean.class, keyValue));

        if (isAdmin) {
            return jdbcTemplate.query("""
                SELECT id, api_key_id, team_id, name, description,
                    threshold_privacy::text AS threshold_privacy,
                    threshold_latency, threshold_accuracy,
                    threshold_cost, threshold_quality, priority, topic
                FROM policies
                """, (rs, n) -> toMap(rs));
        }

        return jdbcTemplate.query("""
            SELECT DISTINCT
                p.id, p.api_key_id, p.team_id, p.name, p.description,
                p.threshold_privacy::text AS threshold_privacy,
                p.threshold_latency, p.threshold_accuracy,
                p.threshold_cost, p.threshold_quality,
                p.priority, p.topic
            FROM policies p
            JOIN api_keys ak ON (p.api_key_id = ak.id OR p.team_id = ak.team_id)
            WHERE ak.key_value = ? AND ak.is_active = true
            """,
            (rs, n) -> toMap(rs), keyValue);
    }

    @Transactional
    public Map<String, Object> addPolicy(String name, String description, String thresholdPrivacy,
                                          int thresholdLatency, int thresholdAccuracy,
                                          int thresholdCost, int thresholdQuality,
                                          int priority, String topic,
                                          Integer apiKeyId, Integer teamId) {
        Integer pk = jdbcTemplate.queryForObject("""
            INSERT INTO policies (name, description, threshold_privacy,
                threshold_latency, threshold_accuracy, threshold_cost, threshold_quality,
                priority, topic, api_key_id, team_id)
            VALUES (?, ?, CAST(? AS threshold_enum), ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """, Integer.class,
            name, description, thresholdPrivacy,
            thresholdLatency, thresholdAccuracy, thresholdCost, thresholdQuality,
            priority, topic, apiKeyId, teamId);
        return Map.of("result", "Created Policy", "policy-id", pk);
    }

    @Transactional
    public Map<String, Object> updatePolicy(int id, String name, String description,
                                             String thresholdPrivacy,
                                             int thresholdLatency, int thresholdAccuracy,
                                             int thresholdCost, int thresholdQuality,
                                             int priority, String topic,
                                             Integer apiKeyId, Integer teamId) {
        jdbcTemplate.update("""
            UPDATE policies SET name=?, description=?, threshold_privacy=CAST(? AS threshold_enum),
                threshold_latency=?, threshold_accuracy=?, threshold_cost=?, threshold_quality=?,
                priority=?, topic=?, api_key_id=?, team_id=?
            WHERE id=?
            """,
            name, description, thresholdPrivacy,
            thresholdLatency, thresholdAccuracy, thresholdCost, thresholdQuality,
            priority, topic, apiKeyId, teamId, id);
        return Map.of("result", "Updated Policy");
    }

    @Transactional
    public Map<String, Object> deletePolicy(int id) {
        jdbcTemplate.update("DELETE FROM policies WHERE id = ?", id);
        return Map.of("result", "Deleted Policy");
    }

    public Optional<Map<String, Object>> getPolicy(int policyId, String keyValue) {
        List<Map<String, Object>> rows = jdbcTemplate.query("""
            SELECT DISTINCT p.id, p.api_key_id, p.team_id, p.name, p.description,
                p.threshold_privacy::text AS threshold_privacy,
                p.threshold_latency, p.threshold_accuracy,
                p.threshold_cost, p.threshold_quality,
                p.priority, p.topic
            FROM policies p
            JOIN api_keys ak ON (p.api_key_id = ak.id OR p.team_id = ak.team_id)
            WHERE ak.key_value = ? AND ak.is_active = true AND p.id = ?
            """,
            (rs, n) -> toMap(rs), keyValue, policyId);

        if (!rows.isEmpty()) return Optional.of(rows.get(0));

        boolean isAdmin = Boolean.TRUE.equals(jdbcTemplate.queryForObject("""
            SELECT COUNT(*) > 0 FROM api_keys ak
            JOIN users u ON ak.user_id = u.id
            WHERE ak.key_value = ? AND u.role = 'logos_admin' AND ak.is_active = true
            """, Boolean.class, keyValue));
        if (isAdmin) {
            List<Map<String, Object>> adminRows = jdbcTemplate.query("""
                SELECT id, api_key_id, team_id, name, description,
                    threshold_privacy::text AS threshold_privacy,
                    threshold_latency, threshold_accuracy,
                    threshold_cost, threshold_quality, priority, topic
                FROM policies WHERE id = ?
                """, (rs, n) -> toMap(rs), policyId);
            return adminRows.isEmpty() ? Optional.empty() : Optional.of(adminRows.get(0));
        }
        return Optional.empty();
    }

    private Map<String, Object> toMap(java.sql.ResultSet rs) throws java.sql.SQLException {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", rs.getInt("id"));
        m.put("api_key_id", rs.getObject("api_key_id"));
        m.put("team_id", rs.getObject("team_id"));
        m.put("name", rs.getString("name"));
        m.put("description", rs.getString("description"));
        m.put("threshold_privacy", rs.getString("threshold_privacy"));
        m.put("threshold_latency", rs.getInt("threshold_latency"));
        m.put("threshold_accuracy", rs.getInt("threshold_accuracy"));
        m.put("threshold_cost", rs.getInt("threshold_cost"));
        m.put("threshold_quality", rs.getInt("threshold_quality"));
        m.put("priority", rs.getInt("priority"));
        m.put("topic", rs.getString("topic"));
        return m;
    }
}
