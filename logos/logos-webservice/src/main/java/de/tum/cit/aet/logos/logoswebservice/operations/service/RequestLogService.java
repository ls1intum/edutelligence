package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class RequestLogService {

    private final JdbcTemplate jdbcTemplate;

    public RequestLogService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Map<String, Object> getLatestRequests() {
        List<Map<String, Object>> rows = jdbcTemplate.query("""
            SELECT le.request_id,
                   COALESCE(m.name, 'Model ' || le.model_id) AS model_name,
                   COALESCE(p.name, 'Provider ' || le.provider_id) AS provider_name,
                   le.result_status::text AS result_status,
                   le.timestamp_request, le.timestamp_forwarding, le.timestamp_response,
                   le.was_cold_start, le.initial_priority, le.priority_when_scheduled,
                   le.queue_depth_at_enqueue, le.error_message,
                   CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding))
                        ELSE NULL END AS run_seconds,
                   CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request))
                        ELSE NULL END AS queue_seconds,
                   CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_response IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request))
                        ELSE NULL END AS total_seconds
            FROM log_entry le
            LEFT JOIN models m ON m.id = le.model_id
            LEFT JOIN providers p ON p.id = le.provider_id
            WHERE le.request_id IS NOT NULL
            ORDER BY le.timestamp_request DESC NULLS LAST
            LIMIT 10
            """,
            (rs, n) -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("request_id", rs.getString("request_id"));
                m.put("model_name", rs.getString("model_name"));
                m.put("provider_name", rs.getString("provider_name"));
                m.put("status", rs.getString("result_status") != null
                                     ? rs.getString("result_status") : "pending");
                m.put("timestamp", ts(rs.getTimestamp("timestamp_request")));
                m.put("enqueue_ts", ts(rs.getTimestamp("timestamp_request")));
                m.put("scheduled_ts", ts(rs.getTimestamp("timestamp_forwarding")));
                m.put("request_complete_ts", ts(rs.getTimestamp("timestamp_response")));
                m.put("duration", nullableDouble(rs, "run_seconds"));
                m.put("cold_start", rs.getObject("was_cold_start"));
                m.put("queue_seconds", nullableDouble(rs, "queue_seconds"));
                m.put("total_seconds", nullableDouble(rs, "total_seconds"));
                m.put("initial_priority", rs.getObject("initial_priority"));
                m.put("priority_when_scheduled", rs.getObject("priority_when_scheduled"));
                m.put("queue_depth_at_enqueue", rs.getObject("queue_depth_at_enqueue"));
                m.put("error_message", rs.getString("error_message"));
                return m;
            });
        return Map.of("requests", rows);
    }

    public Map<String, Object> getRequestLogs(int apiKeyId, List<String> requestIds) {
        if (requestIds.isEmpty()) {
            return Map.of("requests", Collections.emptyList(), "missing_request_ids", Collections.emptyList());
        }
        String placeholders = requestIds.stream().map(id -> "?").collect(Collectors.joining(","));
        List<Object> args = new ArrayList<>();
        args.add(apiKeyId);
        args.addAll(requestIds);

        List<Map<String, Object>> rows = jdbcTemplate.query("""
            SELECT le.request_id,
                   COALESCE(m.name, 'Model ' || le.model_id) AS model_name,
                   COALESCE(p.name, 'Provider ' || le.provider_id) AS provider_name,
                   le.result_status::text AS result_status,
                   le.timestamp_request AS enqueue_ts,
                   le.timestamp_forwarding AS scheduled_ts,
                   le.timestamp_response AS request_complete_ts,
                   le.time_at_first_token,
                   CASE WHEN le.timestamp_request IS NOT NULL AND le.time_at_first_token IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.time_at_first_token - le.timestamp_request)) * 1000
                        ELSE NULL END AS ttft_ms,
                   CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_response IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request)) * 1000
                        ELSE NULL END AS total_latency_ms,
                   CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request)) * 1000
                        ELSE NULL END AS queue_wait_ms,
                   CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding)) * 1000
                        ELSE NULL END AS processing_ms,
                   le.was_cold_start AS cold_start,
                   le.queue_depth_at_arrival, le.utilization_at_arrival,
                   le.queue_depth_at_schedule, le.priority_when_scheduled,
                   le.load_duration_ms, le.available_vram_mb,
                   le.azure_rate_remaining_requests, le.azure_rate_remaining_tokens,
                   le.error_message,
                   MAX(CASE WHEN tt.name = 'prompt_tokens'     THEN ut.token_count END) AS prompt_tokens,
                   MAX(CASE WHEN tt.name = 'completion_tokens' THEN ut.token_count END) AS completion_tokens,
                   MAX(CASE WHEN tt.name = 'total_tokens'      THEN ut.token_count END) AS total_tokens
            FROM log_entry le
            LEFT JOIN models m ON m.id = le.model_id
            LEFT JOIN providers p ON p.id = le.provider_id
            LEFT JOIN usage_tokens ut ON ut.log_entry_id = le.id
            LEFT JOIN token_types tt ON tt.id = ut.type_id
            WHERE le.api_key_id = ?
              AND le.request_id IN (""" + placeholders + """
            )
            GROUP BY le.request_id, m.name, le.model_id, p.name, le.provider_id,
                     le.result_status, le.timestamp_request, le.timestamp_forwarding,
                     le.timestamp_response, le.time_at_first_token, le.was_cold_start,
                     le.queue_depth_at_arrival, le.utilization_at_arrival,
                     le.queue_depth_at_schedule, le.priority_when_scheduled,
                     le.load_duration_ms, le.available_vram_mb,
                     le.azure_rate_remaining_requests, le.azure_rate_remaining_tokens,
                     le.error_message
            ORDER BY le.timestamp_request ASC NULLS LAST
            """,
            args.toArray(),
            (rs, n) -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("request_id", rs.getString("request_id"));
                m.put("status", rs.getString("result_status") != null
                                     ? rs.getString("result_status") : "pending");
                m.put("provider_name", rs.getString("provider_name"));
                m.put("model_name", rs.getString("model_name"));
                m.put("enqueue_ts", ts(rs.getTimestamp("enqueue_ts")));
                m.put("scheduled_ts", ts(rs.getTimestamp("scheduled_ts")));
                m.put("request_complete_ts", ts(rs.getTimestamp("request_complete_ts")));
                m.put("ttft_ms", nullableDouble(rs, "ttft_ms"));
                m.put("total_latency_ms", nullableDouble(rs, "total_latency_ms"));
                m.put("queue_wait_ms", nullableDouble(rs, "queue_wait_ms"));
                m.put("processing_ms", nullableDouble(rs, "processing_ms"));
                m.put("cold_start", rs.getObject("cold_start"));
                m.put("queue_depth_at_arrival", rs.getObject("queue_depth_at_arrival"));
                m.put("utilization_at_arrival", rs.getObject("utilization_at_arrival"));
                m.put("queue_depth_at_schedule", rs.getObject("queue_depth_at_schedule"));
                m.put("priority_when_scheduled", rs.getObject("priority_when_scheduled"));
                m.put("load_duration_ms", rs.getObject("load_duration_ms"));
                m.put("available_vram_mb", rs.getObject("available_vram_mb"));
                m.put("azure_rate_remaining_requests", rs.getObject("azure_rate_remaining_requests"));
                m.put("azure_rate_remaining_tokens", rs.getObject("azure_rate_remaining_tokens"));
                m.put("error_message", rs.getString("error_message"));
                m.put("prompt_tokens", rs.getObject("prompt_tokens"));
                m.put("completion_tokens", rs.getObject("completion_tokens"));
                m.put("total_tokens", rs.getObject("total_tokens"));
                return m;
            });

        List<String> foundIds = rows.stream()
                .map(r -> (String) r.get("request_id"))
                .collect(Collectors.toList());
        List<String> missing = requestIds.stream()
                .filter(id -> !foundIds.contains(id))
                .collect(Collectors.toList());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("requests", rows);
        result.put("missing_request_ids", missing);
        return result;
    }

    public Map<String, Object> getPaginatedRequests(int apiKeyId, int page, int perPage) {
        page = Math.max(1, page);
        perPage = Math.max(1, Math.min(100, perPage));
        int offset = (page - 1) * perPage;

        Long total = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM log_entry WHERE request_id IS NOT NULL AND api_key_id = ?",
                Long.class, apiKeyId);
        if (total == null) total = 0L;
        int totalPages = Math.max(1, (int) ((total + perPage - 1) / perPage));

        List<Map<String, Object>> rows = jdbcTemplate.query("""
            SELECT le.request_id,
                   COALESCE(m.name, 'Model ' || le.model_id) AS model_name,
                   COALESCE(p.name, 'Provider ' || le.provider_id) AS provider_name,
                   p.provider_type::text AS provider_type,
                   le.result_status::text AS result_status,
                   le.timestamp_request AS enqueue_ts,
                   le.timestamp_forwarding AS scheduled_ts,
                   le.timestamp_response AS request_complete_ts,
                   CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding))
                        ELSE NULL END AS run_seconds,
                   CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request))
                        ELSE NULL END AS queue_seconds,
                   CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_response IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_request))
                        ELSE NULL END AS total_seconds,
                   le.was_cold_start AS cold_start, le.initial_priority,
                   le.priority_when_scheduled, le.queue_depth_at_enqueue, le.error_message
            FROM log_entry le
            LEFT JOIN models m ON m.id = le.model_id
            LEFT JOIN providers p ON p.id = le.provider_id
            WHERE le.request_id IS NOT NULL AND le.api_key_id = ?
            ORDER BY le.timestamp_request DESC NULLS LAST
            LIMIT ? OFFSET ?
            """,
            (rs, n) -> {
                Map<String, Object> m = new LinkedHashMap<>();
                String pt = rs.getString("provider_type");
                boolean isCloud = pt != null && !pt.equalsIgnoreCase("logosnode")
                                             && !pt.equalsIgnoreCase("ollama")
                                             && !pt.isEmpty();
                m.put("request_id", rs.getString("request_id"));
                m.put("model_name", rs.getString("model_name"));
                m.put("provider_name", rs.getString("provider_name"));
                m.put("is_cloud", isCloud);
                m.put("status", rs.getString("result_status") != null
                                     ? rs.getString("result_status") : "pending");
                m.put("timestamp", ts(rs.getTimestamp("enqueue_ts")));
                m.put("enqueue_ts", ts(rs.getTimestamp("enqueue_ts")));
                m.put("scheduled_ts", ts(rs.getTimestamp("scheduled_ts")));
                m.put("request_complete_ts", ts(rs.getTimestamp("request_complete_ts")));
                m.put("duration", nullableDouble(rs, "run_seconds"));
                m.put("cold_start", rs.getObject("cold_start"));
                m.put("queue_seconds", nullableDouble(rs, "queue_seconds"));
                m.put("total_seconds", nullableDouble(rs, "total_seconds"));
                m.put("initial_priority", rs.getObject("initial_priority"));
                m.put("priority_when_scheduled", rs.getObject("priority_when_scheduled"));
                m.put("queue_depth_at_enqueue", rs.getObject("queue_depth_at_enqueue"));
                m.put("error_message", rs.getString("error_message"));
                return m;
            },
            apiKeyId, perPage, offset);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("requests", rows);
        result.put("total", total);
        result.put("page", page);
        result.put("per_page", perPage);
        result.put("total_pages", totalPages);
        return result;
    }

    private static String ts(java.sql.Timestamp t) {
        return t != null ? t.toInstant().toString() : null;
    }

    private static Double nullableDouble(java.sql.ResultSet rs, String col)
            throws java.sql.SQLException {
        double v = rs.getDouble(col);
        return rs.wasNull() ? null : v;
    }
}