package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.time.Clock;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/**
 * Approximate monthly budget check for the cloud forward path.
 *
 * <p>Mirrors {@code logos.billing.budget.check_monthly_budget}: application keys
 * use the per-key limit; developer/personal keys check the team monthly cap
 * (developer-key spend only) then the personal/key default limit.
 *
 * <h2>In-memory cache and overshoot bound</h2>
 *
 * <p>Usage and limit lookups are cached per process for
 * {@code logos.gateway.budget-cache-ttl-seconds} (default 15). The gateway is
 * otherwise stateless; this cache is the only budget-related process state.
 *
 * <p><b>Overshoot bound:</b> with TTL {@code T} seconds, a multi-instance
 * deployment (or concurrent requests on one instance after a spend lands in
 * {@code log_entry_cost}) can admit traffic for up to roughly {@code T} seconds
 * after the true budget is exhausted. The admitted overshoot is therefore
 * bounded by concurrent cloud spend in that window — not by an unbounded lag.
 * Example: TTL 15s → overshoot ≲ concurrent spend in any 15s window after the
 * true breach. Lower the TTL to tighten the bound at the cost of more DB load.
 */
@Service
public class GatewayBudgetService {

    private final NamedParameterJdbcTemplate jdbc;
    private final long ttlMillis;
    private final Clock clock;

    /**
     * Process-local budget snapshot cache. Remaining gateway state (none beyond
     * this map and the JDK HttpClient connection pools in the forwarders).
     */
    private final ConcurrentHashMap<String, CacheEntry> cache = new ConcurrentHashMap<>();

    public GatewayBudgetService(
            NamedParameterJdbcTemplate jdbc,
            @Value("${logos.gateway.budget-cache-ttl-seconds:15}") long ttlSeconds) {
        this(jdbc, ttlSeconds, Clock.systemUTC());
    }

    /** Package-private for tests with a fixed clock / TTL. */
    GatewayBudgetService(NamedParameterJdbcTemplate jdbc, long ttlSeconds, Clock clock) {
        this.jdbc = jdbc;
        this.ttlMillis = Math.max(0, ttlSeconds) * 1000L;
        this.clock = clock;
    }

    /**
     * @throws ResponseStatusException 402 when the key/team is over budget
     */
    public void enforceCloudBudget(GatewayKey key) {
        String monthStart = YearMonth.from(LocalDate.now(clock.withZone(ZoneOffset.UTC)))
            .atDay(1)
            .toString();

        if (key.keyType() == ApiKeyType.application) {
            Long limit = apiKeyBudgetLimit(key.id());
            if (limit != null) {
                long used = apiKeyBudgetUsage(key.id(), monthStart);
                if (used >= limit) {
                    throw new ResponseStatusException(
                        HttpStatus.PAYMENT_REQUIRED, "Application monthly budget exceeded.");
                }
            }
            return;
        }

        if (key.teamId() != null) {
            Long teamLimit = teamMonthlyBudget(key.teamId());
            if (teamLimit != null && teamLimit > 0) {
                long teamUsed = teamBudgetUsage(key.teamId(), monthStart);
                if (teamUsed >= teamLimit) {
                    throw new ResponseStatusException(
                        HttpStatus.PAYMENT_REQUIRED,
                        "Team monthly budget exceeded. Contact your admin.");
                }
            }
        }

        Long personalLimit = apiKeyBudgetLimit(key.id());
        if (personalLimit != null) {
            long personalUsed = apiKeyBudgetUsage(key.id(), monthStart);
            if (personalUsed >= personalLimit) {
                throw new ResponseStatusException(
                    HttpStatus.PAYMENT_REQUIRED, "Personal monthly budget exceeded.");
            }
        }
    }

    private Long apiKeyBudgetLimit(int apiKeyId) {
        return cached("limit:key:" + apiKeyId, () -> {
            MapSqlParameterSource params = new MapSqlParameterSource("aki", apiKeyId);
            return jdbc.query("""
                SELECT CAST(ak.settings ->>'budget_limit_micro_cents' AS BIGINT) AS specific_limit,
                       t.default_monthly_budget_micro_cents AS default_limit
                FROM api_keys ak
                LEFT JOIN teams t ON t.id = ak.team_id
                WHERE ak.id = :aki
                """, params, rs -> {
                if (!rs.next()) {
                    return null;
                }
                long specific = rs.getLong("specific_limit");
                if (!rs.wasNull()) {
                    return specific;
                }
                long def = rs.getLong("default_limit");
                return rs.wasNull() ? null : def;
            });
        });
    }

    private long apiKeyBudgetUsage(int apiKeyId, String monthStart) {
        Long v = cached("usage:key:" + apiKeyId + ":" + monthStart, () -> {
            MapSqlParameterSource params = new MapSqlParameterSource()
                .addValue("aki", apiKeyId)
                .addValue("month", monthStart);
            Long total = jdbc.queryForObject("""
                SELECT COALESCE(SUM(lec.cost_micro_cents), 0)
                FROM log_entry_cost lec
                WHERE lec.api_key_id = :aki
                  AND lec.timestamp_request >= CAST(:month AS DATE)
                  AND lec.timestamp_request < CAST(:month AS DATE) + INTERVAL '1 month'
                """, params, Long.class);
            return total == null ? 0L : total;
        });
        return v == null ? 0L : v;
    }

    private Long teamMonthlyBudget(int teamId) {
        return cached("limit:team:" + teamId, () -> {
            MapSqlParameterSource params = new MapSqlParameterSource("tid", teamId);
            return jdbc.query("""
                SELECT team_monthly_budget_micro_cents
                FROM teams WHERE id = :tid
                """, params, rs -> {
                if (!rs.next()) {
                    return null;
                }
                long v = rs.getLong(1);
                return rs.wasNull() ? null : v;
            });
        });
    }

    private long teamBudgetUsage(int teamId, String monthStart) {
        Long v = cached("usage:team:" + teamId + ":" + monthStart, () -> {
            MapSqlParameterSource params = new MapSqlParameterSource()
                .addValue("tid", teamId)
                .addValue("month", monthStart);
            Long total = jdbc.queryForObject("""
                SELECT COALESCE(SUM(lec.cost_micro_cents), 0)
                FROM log_entry_cost lec
                WHERE lec.api_key_id = ANY(
                        ARRAY(SELECT id FROM api_keys WHERE team_id = :tid AND key_type = 'developer')
                      )
                  AND lec.timestamp_request >= CAST(:month AS DATE)
                  AND lec.timestamp_request < CAST(:month AS DATE) + INTERVAL '1 month'
                """, params, Long.class);
            return total == null ? 0L : total;
        });
        return v == null ? 0L : v;
    }

    @SuppressWarnings("unchecked")
    private <T> T cached(String key, Loader<T> loader) {
        if (ttlMillis <= 0) {
            return loader.load();
        }
        long now = clock.millis();
        CacheEntry entry = cache.get(key);
        if (entry != null && now - entry.loadedAtMs < ttlMillis) {
            return (T) entry.value;
        }
        T value = loader.load();
        cache.put(key, new CacheEntry(value, now));
        // Soft bound: drop expired entries opportunistically when the map grows.
        if (cache.size() > 4096) {
            cache.entrySet().removeIf(e -> now - e.getValue().loadedAtMs >= ttlMillis);
        }
        return value;
    }

    @FunctionalInterface
    private interface Loader<T> {
        T load();
    }

    private record CacheEntry(Object value, long loadedAtMs) {
    }

    /** Visible for tests. */
    Map<String, CacheEntry> cacheView() {
        return cache;
    }
}
