package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class EnqueueEventService {

    private final JdbcTemplate jdbc;

    public EnqueueEventService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Map<String, Object> getInRange(String startIso, String endIso, int limit) {
        Instant start = parseIso(startIso);
        Instant end = parseIso(endIso);

        List<Map<String, Object>> rows = jdbc.queryForList("""
            SELECT le.request_id,
                   le.timestamp_request AS enqueue_ts,
                   p.privacy_level
            FROM log_entry le
            LEFT JOIN providers p ON p.id = le.provider_id
            WHERE le.timestamp_request IS NOT NULL
              AND le.request_id IS NOT NULL
              AND le.timestamp_request >= ?
              AND le.timestamp_request <= ?
            ORDER BY le.timestamp_request, le.request_id
            LIMIT ?
            """, Timestamp.from(start), Timestamp.from(end), limit);

        return buildResult(rows, null, "");
    }

    public Map<String, Object> getDeltas(String afterEnqueueTs, String afterRequestId,
                                         String untilTs, int limit) {
        Instant until = untilTs != null ? parseIso(untilTs) : Instant.now();
        String cursorId = afterRequestId != null ? afterRequestId : "";

        List<Map<String, Object>> rows;
        if (afterEnqueueTs == null || afterEnqueueTs.isBlank()) {
            rows = jdbc.queryForList("""
                SELECT le.request_id, le.timestamp_request AS enqueue_ts, p.privacy_level
                FROM log_entry le
                LEFT JOIN providers p ON p.id = le.provider_id
                WHERE le.timestamp_request IS NOT NULL
                  AND le.request_id IS NOT NULL
                  AND le.timestamp_request <= ?
                ORDER BY le.timestamp_request, le.request_id
                LIMIT ?
                """, Timestamp.from(until), limit);
        } else {
            Instant cursor = parseIso(afterEnqueueTs);
            rows = jdbc.queryForList("""
                SELECT le.request_id, le.timestamp_request AS enqueue_ts, p.privacy_level
                FROM log_entry le
                LEFT JOIN providers p ON p.id = le.provider_id
                WHERE le.timestamp_request IS NOT NULL
                  AND le.request_id IS NOT NULL
                  AND (le.timestamp_request, le.request_id::text) > (?, ?)
                  AND le.timestamp_request <= ?
                ORDER BY le.timestamp_request, le.request_id
                LIMIT ?
                """, Timestamp.from(cursor), cursorId, Timestamp.from(until), limit);
        }

        return buildResult(rows, afterEnqueueTs, cursorId);
    }

    private Map<String, Object> buildResult(List<Map<String, Object>> rows,
                                            String initialCursorTs, String initialCursorId) {
        List<Map<String, Object>> events = new ArrayList<>();
        String cursorTs = initialCursorTs;
        String cursorId = initialCursorId;

        for (Map<String, Object> row : rows) {
            Object tsObj = row.get("enqueue_ts");
            Object idObj = row.get("request_id");
            if (tsObj == null || idObj == null) continue;

            Instant ts = tsObj instanceof Timestamp t ? t.toInstant() : parseIso(tsObj.toString());
            String rid = idObj.toString();
            String privacy = (String) row.get("privacy_level");
            boolean isCloud = privacy != null && !"LOCAL".equals(privacy);

            Map<String, Object> e = new LinkedHashMap<>();
            e.put("request_id", rid);
            e.put("enqueue_ts", ts.toString());
            e.put("timestamp_ms", ts.toEpochMilli());
            e.put("is_cloud", isCloud);
            events.add(e);

            cursorTs = ts.toString();
            cursorId = rid;
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("events", events);
        result.put("cursor", Map.of(
            "enqueue_ts", cursorTs != null ? cursorTs : "",
            "request_id", cursorId
        ));
        return result;
    }

    private static Instant parseIso(String iso) {
        if (iso == null || iso.isBlank()) return Instant.now();
        try { return Instant.parse(iso); }
        catch (Exception e) { return ZonedDateTime.parse(iso).toInstant(); }
    }
}
