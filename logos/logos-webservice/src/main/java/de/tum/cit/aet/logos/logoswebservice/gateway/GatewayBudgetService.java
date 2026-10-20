package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.time.Clock;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import de.tum.cit.aet.logos.logoswebservice.common.BackgroundRefreshedCache;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/**
 * Approximate monthly budget check for the cloud forward path.
 *
 * <p>Mirrors {@code logos.billing.budget.check_monthly_budget}: application keys
 * use the per-key limit; developer/personal keys check the team monthly cap
 * (developer-key spend only) then the personal/key default limit. When a
 * {@code team_provider_budgets} row exists for the resolved cloud provider, that
 * provider uses its own cap (null = unlimited / sponsored) and its spend does
 * not draw from the team's default monthly member budget.
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
 * <p>Nothing here serializes admissions on the budget check itself: the
 * snapshot is refreshed at most once per TTL per key (concurrent misses share
 * one load), and a refresh is the only query whose cost grows with the key's
 * month of traffic. No admission waits for that query once a key has a
 * snapshot: an expired snapshot keeps answering while one refresh runs in the
 * background, so the bound above grows by one refresh's duration. Only a key
 * without a snapshot, or one older than
 * {@code logos.gateway.budget-cache-max-stale-seconds} (default 60, the
 * fallback when background refreshes keep failing), loads in line. The
 * mechanics live in {@link BackgroundRefreshedCache}. Reservations noted while
 * a refresh is in flight are queued and merged into the new snapshot so a
 * reload cannot discard them; if the load
 * already counted the same row, the merge double-counts until the next TTL
 * (refuse-more), and the following refresh installs the database total without
 * preserving the inflated value. The bound is the price of that. Trading it for
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
     * Process-local budget snapshots: usage, limits and provider overrides per
     * key or team. The only budget-related process state of the gateway.
     */
    private final BackgroundRefreshedCache cache;

    @Autowired
    public GatewayBudgetService(
            NamedParameterJdbcTemplate jdbc,
            @Value("${logos.gateway.budget-cache-ttl-seconds:15}") long ttlSeconds,
            @Value("${logos.gateway.budget-cache-max-stale-seconds:60}") long maxStaleSeconds) {
        this(jdbc, ttlSeconds, maxStaleSeconds, Clock.systemUTC(), Executors.newVirtualThreadPerTaskExecutor());
    }

    /**
     * Package-private for tests with a fixed clock / TTL. Without a stale
     * window every expired snapshot loads in line.
     */
    GatewayBudgetService(NamedParameterJdbcTemplate jdbc, long ttlSeconds, Clock clock) {
        this(jdbc, ttlSeconds, ttlSeconds, clock, Runnable::run);
    }

    /** Package-private for tests of the background refresh. */
    GatewayBudgetService(NamedParameterJdbcTemplate jdbc, long ttlSeconds, long maxStaleSeconds,
                         Clock clock, Executor refreshExecutor) {
        this.jdbc = jdbc;
        this.ttlMillis = Math.max(0, ttlSeconds) * 1000L;
        this.clock = clock;
        this.cache = new BackgroundRefreshedCache("budget snapshot", ttlMillis,
            Math.max(0, maxStaleSeconds) * 1000L, clock, refreshExecutor);
    }

    /**
     * @throws ResponseStatusException 402 when the key/team is over budget
     */
    public void enforceCloudBudget(GatewayKey key) {
        enforceCloudBudget(key, null);
    }

    /**
     * @param providerId cloud provider for this request; when non-null, a
     *                   {@code team_provider_budgets} row for the team takes
     *                   that provider out of the default team bucket
     * @throws ResponseStatusException 402 when the key/team is over budget
     */
    public void enforceCloudBudget(GatewayKey key, Integer providerId) {
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
            if (providerId != null) {
                ProviderBudgetOverride override = teamProviderBudget(key.teamId(), providerId);
                if (override.exists()) {
                    // Dedicated / sponsored bucket for this provider only.
                    if (override.limitMicroCents() != null) {
                        long used = teamProviderBudgetUsage(key.teamId(), providerId, monthStart);
                        if (used >= override.limitMicroCents()) {
                            throw new ResponseStatusException(
                                HttpStatus.PAYMENT_REQUIRED,
                                "Team monthly budget exceeded for this provider. Contact your admin.");
                        }
                    }
                } else {
                    Long teamLimit = teamMonthlyBudget(key.teamId());
                    if (teamLimit != null && teamLimit > 0) {
                        long teamUsed = teamDefaultBudgetUsage(key.teamId(), monthStart);
                        if (teamUsed >= teamLimit) {
                            throw new ResponseStatusException(
                                HttpStatus.PAYMENT_REQUIRED,
                                "Team monthly budget exceeded. Contact your admin.");
                        }
                    }
                }
            } else {
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
        return cache.get("limit:key:" + apiKeyId, () -> {
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
        Long v = cache.get("usage:key:" + apiKeyId + ":" + monthStart, () -> {
            MapSqlParameterSource params = new MapSqlParameterSource()
                .addValue("aki", apiKeyId)
                .addValue("month", monthStart);
            Long total = jdbc.queryForObject("""
                SELECT {priced} + COALESCE((
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
                """.replace("{priced}", pricedSpend(KEY_FILTER, "")), params, Long.class);
            return total == null ? 0L : total;
        });
        return v == null ? 0L : v;
    }

    private Long teamMonthlyBudget(int teamId) {
        return cache.get("limit:team:" + teamId, () -> {
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

    /**
     * Dedicated per-provider override, if any. {@code exists=false} means the
     * team default bucket applies; {@code exists=true} with a null limit means
     * unlimited for that provider.
     */
    private ProviderBudgetOverride teamProviderBudget(int teamId, int providerId) {
        ProviderBudgetOverride cached = cache.get(
            "limit:team:" + teamId + ":provider:" + providerId,
            () -> {
                MapSqlParameterSource params = new MapSqlParameterSource()
                    .addValue("tid", teamId)
                    .addValue("pid", providerId);
                return jdbc.query("""
                    SELECT monthly_budget_micro_cents
                    FROM team_provider_budgets
                    WHERE team_id = :tid AND provider_id = :pid
                    """, params, rs -> {
                    if (!rs.next()) {
                        return ProviderBudgetOverride.absent();
                    }
                    long v = rs.getLong(1);
                    return ProviderBudgetOverride.present(rs.wasNull() ? null : v);
                });
            });
        return cached == null ? ProviderBudgetOverride.absent() : cached;
    }

    /** Month-to-date developer-key spend for one team; same two parts as {@link #apiKeyBudgetUsage}. */
    private long teamBudgetUsage(int teamId, String monthStart) {
        Long v = cache.get("usage:team:" + teamId + ":" + monthStart, () -> {
            MapSqlParameterSource params = new MapSqlParameterSource()
                .addValue("tid", teamId)
                .addValue("month", monthStart);
            Long total = jdbc.queryForObject("""
                SELECT {priced} + COALESCE((
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
                """.replace("{priced}", pricedSpend(TEAM_FILTER, "")), params, Long.class);
            return total == null ? 0L : total;
        });
        return v == null ? 0L : v;
    }

    /**
     * Developer-key spend that still draws from the team's default monthly
     * budget: everything except providers that have a {@code team_provider_budgets}
     * override row.
     */
    private long teamDefaultBudgetUsage(int teamId, String monthStart) {
        Long v = cache.get("usage:team:" + teamId + ":default:" + monthStart, () -> {
            MapSqlParameterSource params = new MapSqlParameterSource()
                .addValue("tid", teamId)
                .addValue("month", monthStart);
            Long total = jdbc.queryForObject("""
                SELECT {priced} + COALESCE((
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
                      AND (le.provider_id IS NULL OR le.provider_id NOT IN (
                            SELECT provider_id FROM team_provider_budgets WHERE team_id = :tid
                          ))
                ), 0)
                """.replace("{priced}", pricedSpend(TEAM_FILTER, WITHOUT_PROVIDER_OVERRIDE)), params, Long.class);
            return total == null ? 0L : total;
        });
        return v == null ? 0L : v;
    }

    /** Developer-key spend on one provider for the team (settled + in-flight). */
    private long teamProviderBudgetUsage(int teamId, int providerId, String monthStart) {
        Long v = cache.get("usage:team:" + teamId + ":provider:" + providerId + ":" + monthStart, () -> {
            MapSqlParameterSource params = new MapSqlParameterSource()
                .addValue("tid", teamId)
                .addValue("pid", providerId)
                .addValue("month", monthStart);
            Long total = jdbc.queryForObject("""
                SELECT {priced} + COALESCE((
                    SELECT SUM(le.settled_cost_micro_cents)
                    FROM log_entry le
                    WHERE le.api_key_id = ANY(
                            ARRAY(SELECT id FROM api_keys WHERE team_id = :tid AND key_type = 'developer')
                          )
                      AND le.provider_id = :pid
                      AND le.result_status IS NULL
                      AND le.request_id LIKE 'gw-%'
                      AND le.settled_cost_micro_cents IS NOT NULL
                      AND le.settled_cost_micro_cents > 0
                      AND le.timestamp_request >= CAST(:month AS DATE)
                      AND le.timestamp_request < CAST(:month AS DATE) + INTERVAL '1 month'
                ), 0)
                """.replace("{priced}", pricedSpend(TEAM_FILTER, ON_PROVIDER)), params, Long.class);
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
     * <p>If a refresh of this key is in flight, the increment is queued and
     * merged into the new snapshot so the reload cannot discard it. A load that
     * already counted the row can double-count until the next TTL; the next
     * refresh installs the database total and does not preserve the inflated
     * value ({@code Math.max} with a stale entry is intentionally avoided).
     *
     * <p>The team snapshot counts developer-key spend only, so only a
     * developer key's reservation is added to it. A snapshot that is not
     * cached needs nothing: its next load reads the row from the database.
     * When {@code providerId} is set, the bump goes to the provider override
     * bucket if one exists, otherwise to the team default bucket.
     */
    void noteReservation(GatewayKey key, long microCents) {
        noteReservation(key, microCents, null);
    }

    void noteReservation(GatewayKey key, long microCents, Integer providerId) {
        if (key == null || microCents <= 0 || ttlMillis <= 0) {
            return;
        }
        String monthStart = YearMonth.from(LocalDate.now(clock.withZone(ZoneOffset.UTC)))
            .atDay(1)
            .toString();
        addToCachedUsage("usage:key:" + key.id() + ":" + monthStart, microCents);
        if (key.teamId() != null && key.keyType() == ApiKeyType.developer) {
            addToCachedUsage("usage:team:" + key.teamId() + ":" + monthStart, microCents);
            if (providerId != null && teamProviderBudget(key.teamId(), providerId).exists()) {
                addToCachedUsage(
                    "usage:team:" + key.teamId() + ":provider:" + providerId + ":" + monthStart,
                    microCents);
            } else {
                addToCachedUsage(
                    "usage:team:" + key.teamId() + ":default:" + monthStart,
                    microCents);
            }
        }
    }

    private void addToCachedUsage(String cacheKey, long microCents) {
        cache.update(cacheKey, value -> value instanceof Long current ? current + microCents : value);
    }

    private static final String KEY_FILTER = "le.api_key_id = :aki";
    private static final String TEAM_FILTER =
        "le.api_key_id = ANY(ARRAY(SELECT id FROM api_keys WHERE team_id = :tid AND key_type = 'developer'))";
    private static final String WITHOUT_PROVIDER_OVERRIDE =
        "AND (le.provider_id IS NULL OR le.provider_id NOT IN "
            + "(SELECT provider_id FROM team_provider_budgets WHERE team_id = :tid))";
    private static final String ON_PROVIDER = "AND le.provider_id = :pid";

    /**
     * The month's priced spend of the rows {@code keyFilter} and
     * {@code extraFilter} select: what {@code log_entry_cost} sums for them,
     * in two parts. A row whose price is stored ({@code cost_finalized}, the
     * view's first branch) is summed straight from {@code log_entry}; only the
     * rows still unpriced go through the view, which prices them with
     * {@code logos_price_usage}. Summing every row through the view gives the
     * same total, but the planner then costs each row at the pricing
     * function's estimate and JIT-compiles the query, which took longer than
     * the scan itself on a key with a busy month.
     */
    private static String pricedSpend(String keyFilter, String extraFilter) {
        return """
            COALESCE((
                SELECT SUM(le.settled_cost_micro_cents)
                FROM log_entry le
                WHERE {key} {extra}
                  AND le.cost_finalized
                  AND le.result_status IN ('success', 'error', 'timeout')
                  AND le.timestamp_request >= CAST(:month AS DATE)
                  AND le.timestamp_request < CAST(:month AS DATE) + INTERVAL '1 month'
            ), 0) + COALESCE((
                SELECT SUM(lec.cost_micro_cents)
                FROM log_entry_cost lec
                WHERE lec.log_entry_id IN (
                    SELECT le.id
                    FROM log_entry le
                    WHERE {key} {extra}
                      AND le.cost_finalized IS NOT TRUE
                      AND le.result_status IN ('success', 'error', 'timeout')
                      AND le.timestamp_request >= CAST(:month AS DATE)
                      AND le.timestamp_request < CAST(:month AS DATE) + INTERVAL '1 month'
                )
            ), 0)""".replace("{key}", keyFilter).replace("{extra}", extraFilter);
    }

    /**
     * {@code exists} false → use the team default budget; true with a null
     * limit → unlimited for that provider; true with any other limit (0
     * included) → cap.
     */
    record ProviderBudgetOverride(boolean exists, Long limitMicroCents) {
        static ProviderBudgetOverride absent() {
            return new ProviderBudgetOverride(false, null);
        }

        static ProviderBudgetOverride present(Long limitMicroCents) {
            return new ProviderBudgetOverride(true, limitMicroCents);
        }
    }

    /** Visible for tests. */
    Map<String, BackgroundRefreshedCache.Entry> cacheView() {
        return cache.view();
    }
}
