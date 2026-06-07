package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class RequestLogStatsService {

    private static final int[] NICE_BUCKETS = {60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400};
    private static final String TS =
            "COALESCE(timestamp_forwarding, timestamp_request, timestamp_response)";

    private final JdbcTemplate jdbcTemplate;

    public RequestLogStatsService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Map<String, Object> getRequestLogStats(String startDate, String endDate, int targetBuckets) {
        ZonedDateTime now = ZonedDateTime.now(ZoneOffset.UTC);
        ZonedDateTime endDt = endDate != null ? ZonedDateTime.parse(endDate).withZoneSameInstant(ZoneOffset.UTC) : now;
        ZonedDateTime startDt = startDate != null
                ? ZonedDateTime.parse(startDate).withZoneSameInstant(ZoneOffset.UTC)
                : endDt.minusDays(30);

        if (startDt.isAfter(endDt)) {
            throw new IllegalArgumentException("start_date must be before end_date");
        }

        long durationSeconds = Math.max(endDt.toEpochSecond() - startDt.toEpochSecond(), 1);
        int bucketSeconds = chooseBucketSeconds(durationSeconds, Math.max(targetBuckets, 1));

        Timestamp startTs = Timestamp.from(startDt.toInstant());
        Timestamp endTs   = Timestamp.from(endDt.toInstant());

        String lastEventTs = queryLastEventTs(startTs, endTs);
        Map<String, Object> totals = queryTotals(startTs, endTs);
        Map<String, Integer> statusCounts = queryStatusCounts(startTs, endTs);
        List<Map<String, Object>> modelBreakdown = queryModelBreakdown(startTs, endTs);
        List<Map<String, Object>> timeSeries = queryTimeSeries(startTs, endTs, bucketSeconds);
        List<Map<String, Object>> modelTimeSeries = queryModelTimeSeries(startTs, endTs, bucketSeconds);
        Map<String, Object> queueDepth = queryQueueDepth(startTs, endTs);
        List<Map<String, Object>> runtimeByColdStart = queryRuntimeByColdStart(startTs, endTs);

        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("lastEventTs", lastEventTs);
        stats.put("totals", totals);
        stats.put("statusCounts", statusCounts);
        stats.put("modelBreakdown", modelBreakdown);
        stats.put("timeSeries", timeSeries);
        stats.put("modelTimeSeries", modelTimeSeries);
        stats.put("queueDepth", queueDepth);
        stats.put("runtimeByColdStart", runtimeByColdStart);

        Map<String, Object> range = new LinkedHashMap<>();
        range.put("start", startDt.toInstant().toString());
        range.put("end", endDt.toInstant().toString());

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("range", range);
        payload.put("bucketSeconds", bucketSeconds);
        payload.put("stats", stats);
        return payload;
    }

    private String queryLastEventTs(Timestamp start, Timestamp end) {
        Timestamp t = jdbcTemplate.queryForObject(
                "SELECT MAX(" + TS + ") FROM log_entry WHERE " + TS + " BETWEEN ? AND ?",
                Timestamp.class, start, end);
        return t != null ? t.toInstant().toString() : null;
    }

    private Map<String, Object> queryTotals(Timestamp start, Timestamp end) {
        return jdbcTemplate.queryForObject("""
            SELECT COUNT(*) AS requests,
                   COUNT(*) FILTER (WHERE p.privacy_level != 'LOCAL' AND p.privacy_level IS NOT NULL) AS cloud_requests,
                   COUNT(*) FILTER (WHERE p.privacy_level = 'LOCAL' OR p.privacy_level IS NULL) AS local_requests,
                   COUNT(*) FILTER (WHERE was_cold_start IS TRUE) AS cold_starts,
                   COUNT(*) FILTER (WHERE was_cold_start IS NOT TRUE) AS warm_starts,
                   AVG(CASE WHEN le.timestamp_request IS NOT NULL AND le.timestamp_forwarding IS NOT NULL
                       THEN EXTRACT(EPOCH FROM (le.timestamp_forwarding - le.timestamp_request)) END) AS avg_queue_seconds,
                   AVG(CASE WHEN le.timestamp_forwarding IS NOT NULL AND le.timestamp_response IS NOT NULL
                       THEN EXTRACT(EPOCH FROM (le.timestamp_response - le.timestamp_forwarding)) END) AS avg_run_seconds
            FROM log_entry le
            LEFT JOIN providers p ON p.id = le.provider_id
            WHERE %s BETWEEN ? AND ?
            """.formatted(TS),
            (rs, n) -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("requests", rs.getLong("requests"));
                m.put("cloudRequests", rs.getLong("cloud_requests"));
                m.put("localRequests", rs.getLong("local_requests"));
                m.put("coldStarts", rs.getLong("cold_starts"));
                m.put("warmStarts", rs.getLong("warm_starts"));
                m.put("avgQueueSeconds", nullableDouble(rs, "avg_queue_seconds"));
                m.put("avgRunSeconds", nullableDouble(rs, "avg_run_seconds"));
                return m;
            },
            start, end);
    }

    private Map<String, Integer> queryStatusCounts(Timestamp start, Timestamp end) {
        Map<String, Integer> counts = new LinkedHashMap<>();
        jdbcTemplate.query("""
            SELECT COALESCE(result_status::text, 'unknown') AS status, COUNT(*) AS cnt
            FROM log_entry
            WHERE %s BETWEEN ? AND ?
            GROUP BY 1
            """.formatted(TS),
            rs -> { counts.put(rs.getString("status").toLowerCase(), rs.getInt("cnt")); },
            start, end);
        return counts;
    }

    private List<Map<String, Object>> queryModelBreakdown(Timestamp start, Timestamp end) {
        return jdbcTemplate.query("""
            SELECT re.model_id,
                   COALESCE(m.name, 'Model ' || re.model_id) AS model_name,
                   COALESCE(p.name, 'Provider ' || re.provider_id) AS provider_name,
                   COUNT(*) AS request_count,
                   AVG(CASE WHEN re.timestamp_request IS NOT NULL AND re.timestamp_forwarding IS NOT NULL
                       THEN EXTRACT(EPOCH FROM (re.timestamp_forwarding - re.timestamp_request)) END) AS avg_queue_seconds,
                   AVG(CASE WHEN re.timestamp_forwarding IS NOT NULL AND re.timestamp_response IS NOT NULL
                       THEN EXTRACT(EPOCH FROM (re.timestamp_response - re.timestamp_forwarding)) END) AS avg_run_seconds,
                   SUM(CASE WHEN re.was_cold_start IS TRUE THEN 1 ELSE 0 END) AS cold_starts,
                   SUM(CASE WHEN re.was_cold_start IS NOT TRUE THEN 1 ELSE 0 END) AS warm_starts,
                   SUM(CASE WHEN re.result_status IS DISTINCT FROM 'success'
                                  OR (re.error_message IS NOT NULL AND re.error_message != '')
                            THEN 1 ELSE 0 END) AS error_count
            FROM log_entry re
            LEFT JOIN models m ON m.id = re.model_id
            LEFT JOIN providers p ON p.id = re.provider_id
            WHERE %s BETWEEN ? AND ?
            GROUP BY re.model_id, model_name, re.provider_id, provider_name
            ORDER BY request_count DESC
            """.formatted(TS),
            (rs, n) -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("modelId", rs.getObject("model_id") != null ? rs.getInt("model_id") : -1);
                m.put("modelName", rs.getString("model_name"));
                m.put("providerName", rs.getString("provider_name"));
                m.put("requestCount", rs.getLong("request_count"));
                m.put("avgQueueSeconds", nullableDouble(rs, "avg_queue_seconds"));
                m.put("avgRunSeconds", nullableDouble(rs, "avg_run_seconds"));
                m.put("coldStarts", rs.getLong("cold_starts"));
                m.put("warmStarts", rs.getLong("warm_starts"));
                m.put("errorCount", rs.getLong("error_count"));
                return m;
            },
            start, end);
    }

    private List<Map<String, Object>> queryTimeSeries(Timestamp start, Timestamp end, int bucketSeconds) {
        String sql = """
            WITH bucket_series AS (
                SELECT generate_series(
                    to_timestamp(FLOOR(EXTRACT(EPOCH FROM ?::timestamptz) / %d) * %d),
                    to_timestamp(FLOOR(EXTRACT(EPOCH FROM ?::timestamptz) / %d) * %d),
                    ('%d seconds')::interval
                ) AS bucket_ts
            ),
            agg AS (
                SELECT to_timestamp(FLOOR(EXTRACT(EPOCH FROM %s) / %d) * %d) AS bucket_ts,
                       COUNT(*) AS total,
                       SUM(CASE WHEN p.privacy_level != 'LOCAL' AND p.privacy_level IS NOT NULL THEN 1 ELSE 0 END) AS cloud,
                       SUM(CASE WHEN p.privacy_level = 'LOCAL' OR p.privacy_level IS NULL THEN 1 ELSE 0 END) AS local,
                       AVG(CASE WHEN re.timestamp_forwarding IS NOT NULL AND re.timestamp_response IS NOT NULL
                           THEN EXTRACT(EPOCH FROM (re.timestamp_response - re.timestamp_forwarding)) END) AS avg_run_seconds,
                       AVG(re.available_vram_mb) AS avg_vram
                FROM log_entry re
                LEFT JOIN providers p ON p.id = re.provider_id
                WHERE %s BETWEEN ? AND ?
                GROUP BY 1
            )
            SELECT EXTRACT(EPOCH FROM bs.bucket_ts) AS bucket_ts,
                   COALESCE(agg.total, 0) AS total,
                   COALESCE(agg.cloud, 0) AS cloud,
                   COALESCE(agg.local, 0) AS local,
                   agg.avg_run_seconds,
                   agg.avg_vram
            FROM bucket_series bs
            LEFT JOIN agg ON agg.bucket_ts = bs.bucket_ts
            ORDER BY bs.bucket_ts
            """.formatted(bucketSeconds, bucketSeconds, bucketSeconds, bucketSeconds,
                          bucketSeconds, TS, bucketSeconds, bucketSeconds, TS);

        return jdbcTemplate.query(sql,
            (rs, n) -> {
                double bucketEpoch = rs.getDouble("bucket_ts");
                if (rs.wasNull()) return null;
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("timestamp", (long) bucketEpoch * 1000L);
                m.put("label", "");
                m.put("cloud", rs.getLong("cloud"));
                m.put("local", rs.getLong("local"));
                m.put("total", rs.getLong("total"));
                m.put("avgRunSeconds", nullableDouble(rs, "avg_run_seconds"));
                m.put("avgVram", nullableDouble(rs, "avg_vram"));
                return m;
            },
            start, end, start, end);
    }

    private List<Map<String, Object>> queryModelTimeSeries(Timestamp start, Timestamp end, int bucketSeconds) {
        String sql = """
            SELECT EXTRACT(EPOCH FROM to_timestamp(FLOOR(EXTRACT(EPOCH FROM %s) / %d) * %d)) AS bucket_ts,
                   re.model_id,
                   COALESCE(m.name, 'Model ' || re.model_id) AS model_name,
                   COUNT(*) AS count
            FROM log_entry re
            LEFT JOIN models m ON m.id = re.model_id
            WHERE %s BETWEEN ? AND ?
              AND re.model_id IS NOT NULL
            GROUP BY 1, re.model_id, m.name
            ORDER BY 1, model_name
            """.formatted(TS, bucketSeconds, bucketSeconds, TS);

        List<Map<String, Object>> result = new ArrayList<>();
        jdbcTemplate.query(sql,
            rs -> {
                double bucketEpoch = rs.getDouble("bucket_ts");
                if (rs.wasNull()) return;
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("timestamp", (long) bucketEpoch * 1000L);
                m.put("modelId", rs.getInt("model_id"));
                m.put("modelName", rs.getString("model_name"));
                m.put("count", rs.getLong("count"));
                result.add(m);
            },
            start, end);
        return result;
    }

    private Map<String, Object> queryQueueDepth(Timestamp start, Timestamp end) {
        return jdbcTemplate.queryForObject("""
            SELECT AVG(queue_depth_at_enqueue) AS avg_enqueue,
                   AVG(queue_depth_at_schedule) AS avg_schedule,
                   PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY queue_depth_at_enqueue) AS p95_enqueue,
                   PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY queue_depth_at_schedule) AS p95_schedule
            FROM log_entry
            WHERE %s BETWEEN ? AND ?
              AND (queue_depth_at_enqueue IS NOT NULL OR queue_depth_at_schedule IS NOT NULL)
            """.formatted(TS),
            (rs, n) -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("avgEnqueueDepth", nullableDouble(rs, "avg_enqueue"));
                m.put("avgScheduleDepth", nullableDouble(rs, "avg_schedule"));
                m.put("p95EnqueueDepth", nullableDouble(rs, "p95_enqueue"));
                m.put("p95ScheduleDepth", nullableDouble(rs, "p95_schedule"));
                return m;
            },
            start, end);
    }

    private List<Map<String, Object>> queryRuntimeByColdStart(Timestamp start, Timestamp end) {
        return jdbcTemplate.query("""
            SELECT CASE WHEN was_cold_start IS TRUE THEN 'cold' ELSE 'warm' END AS kind,
                   COUNT(*) AS count,
                   AVG(CASE WHEN timestamp_forwarding IS NOT NULL AND timestamp_response IS NOT NULL
                       THEN EXTRACT(EPOCH FROM (timestamp_response - timestamp_forwarding)) END) AS avg_run_seconds
            FROM log_entry
            WHERE %s BETWEEN ? AND ?
            GROUP BY kind
            """.formatted(TS),
            (rs, n) -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("type", rs.getString("kind"));
                m.put("avgRunSeconds", nullableDouble(rs, "avg_run_seconds"));
                m.put("count", rs.getLong("count"));
                return m;
            },
            start, end);
    }

    static int chooseBucketSeconds(long durationSeconds, int targetBuckets) {
        double rawBucket = Math.max((double) durationSeconds / targetBuckets, 60);
        int best = NICE_BUCKETS[0];
        double bestDiff = Math.abs(rawBucket - best);
        for (int c : NICE_BUCKETS) {
            double diff = Math.abs(rawBucket - c);
            if (diff < bestDiff) { best = c; bestDiff = diff; }
        }
        return best;
    }

    private static Double nullableDouble(ResultSet rs, String col) throws SQLException {
        double v = rs.getDouble(col);
        return rs.wasNull() ? null : v;
    }
}