package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.Timestamp;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class BillingService {

    private static final Map<Integer, String> BUCKET_TO_PG_INTERVAL = Map.of(
            3600, "hour",
            86400, "day",
            604800, "week",
            2592000, "month"
    );

    private final JdbcTemplate jdbcTemplate;

    public BillingService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Map<String, Object> addBilling(String typeName, double typeCost,
                                          String validFrom, Integer modelId) {
        List<Integer> ids = jdbcTemplate.queryForList("SELECT id FROM token_types WHERE name = ?", Integer.class, typeName);
        if (ids.isEmpty()) {
            throw new IllegalArgumentException("Token name not found");
        }
        Integer typeId = ids.get(0);
        Timestamp ts = Timestamp.from(
                ZonedDateTime.parse(validFrom.replace("Z", "+00:00"))
                             .withZoneSameInstant(ZoneOffset.UTC).toInstant());

        if (modelId != null) {
            Long billingId = jdbcTemplate.queryForObject("""
                INSERT INTO token_prices (type_id, valid_from, price_per_k_token, model_id)
                VALUES (?, ?, ?, ?)
                RETURNING id
                """, Long.class, typeId, ts, Math.round(typeCost), modelId);
            return Map.of("result", "Successfully added billing", "billing-id", billingId);
        } else {
            Long billingId = jdbcTemplate.queryForObject("""
                INSERT INTO token_prices (type_id, valid_from, price_per_k_token)
                VALUES (?, ?, ?)
                RETURNING id
                """, Long.class, typeId, ts, Math.round(typeCost));
            return Map.of("result", "Successfully added billing", "billing-id", billingId);
        }
    }

    public Map<String, Object> getTeamBudgetHistory(String startIso, String endIso) {
        Timestamp startTs = isoToTimestamp(startIso);
        Timestamp endTs = isoToTimestamp(endIso);
        long spanSeconds = spanSeconds(startIso, endIso);
        int bucketSeconds = chooseBillingBucketSeconds(spanSeconds);
        String interval = BUCKET_TO_PG_INTERVAL.getOrDefault(bucketSeconds, "day");

        List<Map<String, Object>> buckets = jdbcTemplate.query("""
            SELECT t.id AS team_id,
                   t.name AS team_name,
                   DATE_TRUNC('""" + interval + """
            ', le.timestamp_request) AS bucket_ts,
                   COALESCE(SUM(
                       CASE WHEN tp.price_per_k_token IS NOT NULL
                            THEN (ut.token_count::BIGINT * tp.price_per_k_token / 1000)::BIGINT
                            ELSE 0
                       END
                   ), 0) AS cost_micro_cents
            FROM log_entry le
            JOIN api_keys ak ON ak.id = le.api_key_id
            JOIN teams t ON t.id = ak.team_id
            JOIN usage_tokens ut ON ut.log_entry_id = le.id
            LEFT JOIN LATERAL (
                SELECT price_per_k_token
                FROM token_prices
                WHERE type_id = ut.type_id
                  AND (model_id = le.model_id OR model_id IS NULL)
                  AND (provider_id = le.provider_id OR provider_id IS NULL)
                  AND valid_from <= le.timestamp_request
                ORDER BY (model_id = le.model_id) DESC NULLS LAST,
                         (provider_id = le.provider_id) DESC NULLS LAST,
                         valid_from DESC
                LIMIT 1
            ) tp ON true
            WHERE le.timestamp_request >= ? AND le.timestamp_request < ?
              AND le.api_key_id IS NOT NULL
            GROUP BY t.id, t.name, DATE_TRUNC('""" + interval + """
            ', le.timestamp_request)
            ORDER BY bucket_ts, t.name
            """,
            (rs, n) -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("team_id", rs.getInt("team_id"));
                m.put("team_name", rs.getString("team_name"));
                m.put("bucket_ts", ts(rs.getTimestamp("bucket_ts")));
                m.put("cost_micro_cents", rs.getLong("cost_micro_cents"));
                return m;
            },
            startTs, endTs);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("buckets", buckets);
        result.put("bucket_seconds", bucketSeconds);
        result.put("start_iso", startIso);
        result.put("end_iso", endIso);
        return result;
    }

    public Map<String, Object> getKeyBudgetHistory(int teamId, String startIso, String endIso) {
        Timestamp startTs = isoToTimestamp(startIso);
        Timestamp endTs = isoToTimestamp(endIso);
        long spanSeconds = spanSeconds(startIso, endIso);
        int bucketSeconds = chooseBillingBucketSeconds(spanSeconds);
        String interval = BUCKET_TO_PG_INTERVAL.getOrDefault(bucketSeconds, "day");

        List<Map<String, Object>> buckets = jdbcTemplate.query("""
            SELECT ak.id AS api_key_id,
                   ak.name AS api_key_name,
                   DATE_TRUNC('""" + interval + """
            ', le.timestamp_request) AS bucket_ts,
                   COALESCE(SUM(
                       CASE WHEN tp.price_per_k_token IS NOT NULL
                            THEN (ut.token_count::BIGINT * tp.price_per_k_token / 1000)::BIGINT
                            ELSE 0
                       END
                   ), 0) AS cost_micro_cents
            FROM log_entry le
            JOIN api_keys ak ON ak.id = le.api_key_id
            JOIN usage_tokens ut ON ut.log_entry_id = le.id
            LEFT JOIN LATERAL (
                SELECT price_per_k_token
                FROM token_prices
                WHERE type_id = ut.type_id
                  AND (model_id = le.model_id OR model_id IS NULL)
                  AND (provider_id = le.provider_id OR provider_id IS NULL)
                  AND valid_from <= le.timestamp_request
                ORDER BY (model_id = le.model_id) DESC NULLS LAST,
                         (provider_id = le.provider_id) DESC NULLS LAST,
                         valid_from DESC
                LIMIT 1
            ) tp ON true
            WHERE ak.team_id = ?
              AND le.timestamp_request >= ? AND le.timestamp_request < ?
              AND le.api_key_id IS NOT NULL
            GROUP BY ak.id, ak.name, DATE_TRUNC('""" + interval + """
            ', le.timestamp_request)
            ORDER BY bucket_ts, ak.name
            """,
            (rs, n) -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("api_key_id", rs.getInt("api_key_id"));
                m.put("api_key_name", rs.getString("api_key_name"));
                m.put("bucket_ts", ts(rs.getTimestamp("bucket_ts")));
                m.put("cost_micro_cents", rs.getLong("cost_micro_cents"));
                return m;
            },
            teamId, startTs, endTs);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("buckets", buckets);
        result.put("bucket_seconds", bucketSeconds);
        result.put("start_iso", startIso);
        result.put("end_iso", endIso);
        return result;
    }

    static int chooseBillingBucketSeconds(long spanSeconds) {
        long day = 86400;
        if (spanSeconds <= day) return 3600;
        if (spanSeconds <= 32 * day) return 86400;
        if (spanSeconds <= 186 * day) return 604800;
        return 2592000;
    }

    private static long spanSeconds(String startIso, String endIso) {
        ZonedDateTime start = ZonedDateTime.parse(startIso.replace("Z", "+00:00"))
                                           .withZoneSameInstant(ZoneOffset.UTC);
        ZonedDateTime end   = ZonedDateTime.parse(endIso.replace("Z", "+00:00"))
                                           .withZoneSameInstant(ZoneOffset.UTC);
        return Math.max(end.toEpochSecond() - start.toEpochSecond(), 0);
    }

    private static Timestamp isoToTimestamp(String iso) {
        return Timestamp.from(ZonedDateTime.parse(iso.replace("Z", "+00:00"))
                                        .withZoneSameInstant(ZoneOffset.UTC).toInstant());
    }

    private static String ts(java.sql.Timestamp t) {
        return t != null ? t.toInstant().toString() : null;
    }
}
