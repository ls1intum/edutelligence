package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.time.Clock;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.beans.factory.annotation.Autowired;
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
 * after the true budget is exhausted. On the direct-cloud path
 * {@link GatewayCloudAccounting} writes an in-flight reservation into
 * {@code log_entry} (counted by this service alongside {@code log_entry_cost})
 * before the upstream call and adds it to this instance's cached snapshot via
 * {@link #noteReservation}, so later admissions on the same instance see it
 * without a database round trip; other instances pick it up when their
 * snapshots expire. A reservation counts only while the request is in flight:
 * once settled, the row is priced from its token usage and reaches this
 * service through {@code log_entry_cost} like any other request. Example:
 * TTL 15s → overshoot ≲ spend admitted in any 15s window after the true
 * breach, plus one reservation per request admitted on other instances in
 * that window. Lower the TTL to tighten the bound at the cost of more DB load.
 *
 * <p>Nothing here serializes requests: the snapshot is refreshed at most once
 * per TTL per key, and a refresh is the only query whose cost grows with the
 * key's month of traffic. The bound is the price of that. Trading it for
 * exactness — a per-key lock around check-and-reserve, or a snapshot reload
 * per request — makes every request on a key wait for a full re-pricing of
 * that key's month, so admission time grows with the log; do not.
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

    @Autowired
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

    /**
     * Month-to-date spend for one key: priced requests from
     * {@code log_entry_cost} plus the direct-cloud reservations still in flight,
     * which no price exists for yet.
     */
    private long apiKeyBudgetUsage(int apiKeyId, String monthStart) {
        Long v = cached("usage:key:" + apiKeyId + ":" + monthStart, () -> {
            MapSqlParameterSource params = new MapSqlParameterSource()
                .addValue("aki", apiKeyId)
                .addValue("month", monthStart);
            Long total = jdbc.queryForObject("""
                SELECT COALESCE((
                    SELECT SUM(lec.cost_micro_cents)
                    FROM log_entry_cost lec
                    WHERE lec.api_key_id = :aki
                      AND lec.timestamp_request >= CAST(:month AS DATE)
                      AND lec.timestamp_request < CAST(:month AS DATE) + INTERVAL '1 month'
                ), 0) + COALESCE((
                    SELECT SUM(le.settled_cost_micro_cents)
                    FROM log_entry le
                    WHERE le.api_key_id = :aki
                      AND le.result_status IS NULL
                      AND le.request_id LIKE 'gw-%'
                      AND le.settled_cost_micro_cents IS NOT NULL
                      AND le.settled_cost_micro_cents > 0
                      AND le.timestamp_request >= CAST(:month AS DATE)
                      AND le.timestamp_request < CAST(:month AS DATE) + INTERVAL '1 month'
                ), 0)
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

    /** Month-to-date developer-key spend for one team; same two parts as {@link #apiKeyBudgetUsage}. */
    private long teamBudgetUsage(int teamId, String monthStart) {
        Long v = cached("usage:team:" + teamId + ":" + monthStart, () -> {
            MapSqlParameterSource params = new MapSqlParameterSource()
                .addValue("tid", teamId)
                .addValue("month", monthStart);
            Long total = jdbc.queryForObject("""
                SELECT COALESCE((
                    SELECT SUM(lec.cost_micro_cents)
                    FROM log_entry_cost lec
                    WHERE lec.api_key_id = ANY(
                            ARRAY(SELECT id FROM api_keys WHERE team_id = :tid AND key_type = 'developer')
                          )
                      AND lec.timestamp_request >= CAST(:month AS DATE)
                      AND lec.timestamp_request < CAST(:month AS DATE) + INTERVAL '1 month'
                ), 0) + COALESCE((
                    SELECT SUM(le.settled_cost_micro_cents)
                    FROM log_entry le
                    WHERE le.api_key_id = ANY(
                            ARRAY(SELECT id FROM api_keys WHERE team_id = :tid AND key_type = 'developer')
                          )
                      AND le.result_status IS NULL
                      AND le.request_id LIKE 'gw-%'
                      AND le.settled_cost_micro_cents IS NOT NULL
                      AND le.settled_cost_micro_cents > 0
                      AND le.timestamp_request >= CAST(:month AS DATE)
                      AND le.timestamp_request < CAST(:month AS DATE) + INTERVAL '1 month'
                ), 0)
                """, params, Long.class);
            return total == null ? 0L : total;
        });
        return v == null ? 0L : v;
    }

    /**
     * Add a reservation just written for this key to the cached month-to-date
     * usage, so the next admission on this instance counts it.
     *
     * <p>Adjusts the snapshot in place instead of dropping it: a drop would
     * make the next request re-price the key's whole month, and admission
     * must not do work that grows with the log. The entry
     * keeps its load time, so the snapshot still expires — and is then read
     * back from the database, where the reservation row is counted while in
     * flight and the settled charge after — on the same schedule as before.
     * Until then the snapshot may over-count a request that has already
     * settled, which errs towards refusing, never towards overspend.
     *
     * <p>The team snapshot counts developer-key spend only, so only a
     * developer key's reservation is added to it. A snapshot that is not
     * cached needs nothing: its next load reads the row from the database.
     */
    void noteReservation(GatewayKey key, long microCents) {
        if (key == null || microCents <= 0 || ttlMillis <= 0) {
            return;
        }
        String monthStart = YearMonth.from(LocalDate.now(clock.withZone(ZoneOffset.UTC)))
            .atDay(1)
            .toString();
        addToCachedUsage("usage:key:" + key.id() + ":" + monthStart, microCents);
        if (key.teamId() != null && key.keyType() == ApiKeyType.developer) {
            addToCachedUsage("usage:team:" + key.teamId() + ":" + monthStart, microCents);
        }
    }

    private void addToCachedUsage(String cacheKey, long microCents) {
        cache.computeIfPresent(cacheKey, (k, entry) -> {
            long current = entry.value instanceof Long l ? l : 0L;
            return new CacheEntry(current + microCents, entry.loadedAtMs);
        });
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
