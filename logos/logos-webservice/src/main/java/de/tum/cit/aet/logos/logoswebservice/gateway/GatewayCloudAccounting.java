package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

/**
 * Budget-visible accounting for the direct-cloud path.
 *
 * <p>{@link #admitAndReserve} locks the API key row, checks budget, optionally
 * enforces a shared RPM window from {@code log_entry}, then inserts an in-flight
 * reservation ({@code result_status IS NULL}) so concurrent admissions cannot
 * both pass the same check. {@link #reconcileStale} zeros abandoned rows after
 * process loss.
 *
 * <p>On success the reservation is replaced by the real charge: the reported
 * token counts are written to {@code usage_tokens} and the row is un-finalized,
 * which hands pricing to {@code logos_price_usage} through the
 * {@code log_entry_cost} view — the same computation the orchestrator path
 * settles with. Only a response that reports no usage at all keeps the flat
 * reservation, and failure zeros it.
 */
@Service
public class GatewayCloudAccounting {

    private final NamedParameterJdbcTemplate jdbc;
    private final GatewayBudgetService budgetService;
    private final long reservationMicroCents;
    private final int staleAfterMinutes;

    public GatewayCloudAccounting(
            NamedParameterJdbcTemplate jdbc,
            GatewayBudgetService budgetService,
            @Value("${logos.gateway.budget-reservation-micro-cents:1000000}") long reservationMicroCents,
            @Value("${logos.gateway.budget-reservation-stale-minutes:30}") int staleAfterMinutes) {
        this.jdbc = jdbc;
        this.budgetService = budgetService;
        this.reservationMicroCents = Math.max(0L, reservationMicroCents);
        this.staleAfterMinutes = Math.max(1, staleAfterMinutes);
    }

    /**
     * Atomically check budget (and optional shared RPM) then insert an in-flight
     * reservation. Serializes per API key via {@code SELECT … FOR UPDATE}.
     *
     * @param sharedRpmLimit per-key cloud RPM across replicas, or {@code null}
     * @return log_entry id, or {@code null} when reservation amount is 0
     */
    @Transactional
    public Integer admitAndReserve(GatewayKey key, GatewayDeployment deployment, Integer sharedRpmLimit) {
        MapSqlParameterSource lockParams = new MapSqlParameterSource("aki", key.id());
        Integer locked = jdbc.query("""
            SELECT id FROM api_keys WHERE id = :aki FOR UPDATE
            """, lockParams, rs -> rs.next() ? rs.getInt(1) : null);
        if (locked == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid or missing API key");
        }

        reconcileStale();
        budgetService.invalidateUsageCache(key);
        budgetService.enforceCloudBudget(key);

        if (sharedRpmLimit != null && sharedRpmLimit > 0) {
            MapSqlParameterSource rpmParams = new MapSqlParameterSource()
                .addValue("aki", key.id())
                .addValue("window", GatewayCloudRateLimiter.WINDOW_SECONDS);
            Integer recent = jdbc.queryForObject("""
                SELECT COUNT(*)::int
                FROM log_entry
                WHERE api_key_id = :aki
                  AND request_id LIKE 'gw-%%'
                  AND timestamp_request > NOW() - make_interval(secs => :window)
                """, rpmParams, Integer.class);
            if (recent != null && recent >= sharedRpmLimit) {
                throw new ResponseStatusException(
                    HttpStatus.TOO_MANY_REQUESTS,
                    "RPM limit reached (" + sharedRpmLimit + "/"
                        + GatewayCloudRateLimiter.WINDOW_SECONDS + "s)");
            }
        }

        if (reservationMicroCents <= 0) {
            return null;
        }
        String requestId = "gw-" + UUID.randomUUID();
        MapSqlParameterSource params = new MapSqlParameterSource()
            .addValue("request_id", requestId)
            .addValue("api_key_id", key.id())
            .addValue("team_id", key.teamId())
            .addValue("user_id", key.userId())
            .addValue("environment", key.environment())
            .addValue("model_id", deployment.modelId())
            .addValue("provider_id", deployment.providerId())
            .addValue("settled", reservationMicroCents);
        KeyHolder keys = new GeneratedKeyHolder();
        jdbc.update("""
            INSERT INTO log_entry (
                timestamp_request, timestamp_forwarding,
                api_key_id, team_id, user_id, environment,
                model_id, provider_id, request_id,
                result_status, cost_finalized, settled_cost_micro_cents,
                privacy_level
            ) VALUES (
                NOW(), NOW(),
                :api_key_id, :team_id, :user_id, :environment,
                :model_id, :provider_id, :request_id,
                NULL, TRUE, :settled,
                'BILLING'
            )
            """, params, keys, new String[] {"id"});
        Number id = keys.getKey();
        budgetService.invalidateUsageCache(key);
        return id == null ? null : id.intValue();
    }

    /**
     * Settle the in-flight reservation as a success.
     *
     * <p>With usage reported, the row is un-finalized after the token counts
     * are stored, so {@code log_entry_cost} prices it from
     * {@code logos_price_usage} instead of the reservation. Without usage —
     * a streaming upstream that ignored {@code include_usage}, a body past the
     * capture cap — the flat reservation stands, because an unpriced success
     * must not read as free budget.
     *
     * @param usage canonical token counts, empty when the response reported none
     */
    @Transactional
    public void settleSuccess(Integer logEntryId, Map<String, Long> usage) {
        if (logEntryId == null) {
            return;
        }
        boolean priced = usage != null && !usage.isEmpty();
        // Claim the row first: a reservation already zeroed by reconcileStale
        // (or settled by a racing callback) must not gain usage rows.
        int claimed = jdbc.update(priced ? """
            UPDATE log_entry
               SET timestamp_response = NOW(),
                   result_status = 'success',
                   settled_cost_micro_cents = NULL,
                   cost_finalized = FALSE
             WHERE id = :id
               AND result_status IS NULL
            """ : """
            UPDATE log_entry
               SET timestamp_response = NOW(),
                   result_status = 'success',
                   cost_finalized = TRUE
             WHERE id = :id
               AND result_status IS NULL
            """, new MapSqlParameterSource("id", logEntryId));
        if (claimed == 0 || !priced) {
            return;
        }
        upsertUsageTokens(logEntryId, usage);
    }

    /**
     * Store the canonical token counts for one log row.
     *
     * <p>Mirrors the orchestrator's upsert: every reported name registers its
     * type (auto-creating one the deployment has not reported before), and the
     * usage rows are replayable — a retried settle overwrites rather than
     * duplicates.
     */
    private void upsertUsageTokens(int logEntryId, Map<String, Long> usage) {
        Map<String, Integer> counts = new LinkedHashMap<>();
        for (Map.Entry<String, Long> e : usage.entrySet()) {
            String name = e.getKey();
            Long value = e.getValue();
            if (name == null || name.isBlank() || value == null || value <= 0) {
                continue;
            }
            // token_count is an int column; a count past that range is a
            // provider bug, not a quantity worth billing.
            if (value > Integer.MAX_VALUE) {
                continue;
            }
            counts.put(name, value.intValue());
        }
        if (counts.isEmpty()) {
            return;
        }

        List<String> names = new ArrayList<>(counts.keySet());
        insertMissingTokenTypes(names);
        Map<String, Integer> typeIds = tokenTypeIds(names);

        List<String> values = new ArrayList<>();
        MapSqlParameterSource params = new MapSqlParameterSource("log", logEntryId);
        int index = 0;
        for (Map.Entry<String, Integer> e : counts.entrySet()) {
            Integer typeId = typeIds.get(e.getKey());
            if (typeId == null) {
                continue;
            }
            values.add("(:log, :t" + index + ", :c" + index + ")");
            params.addValue("t" + index, typeId);
            params.addValue("c" + index, e.getValue());
            index++;
        }
        if (values.isEmpty()) {
            return;
        }
        jdbc.update("""
            INSERT INTO usage_tokens (log_entry_id, type_id, token_count)
            VALUES %s
            ON CONFLICT (log_entry_id, type_id)
            DO UPDATE SET token_count = EXCLUDED.token_count
            """.formatted(String.join(", ", values)), params);
    }

    /** Register token type names not seen before. {@code name} is UNIQUE, so this is race-safe. */
    private void insertMissingTokenTypes(List<String> names) {
        List<String> values = new ArrayList<>();
        MapSqlParameterSource params = new MapSqlParameterSource();
        for (int i = 0; i < names.size(); i++) {
            values.add("(:n" + i + ", '')");
            params.addValue("n" + i, names.get(i));
        }
        jdbc.update("""
            INSERT INTO token_types (name, description)
            VALUES %s
            ON CONFLICT (name) DO NOTHING
            """.formatted(String.join(", ", values)), params);
    }

    private Map<String, Integer> tokenTypeIds(List<String> names) {
        Map<String, Integer> ids = new LinkedHashMap<>();
        jdbc.query(
            "SELECT id, name FROM token_types WHERE name IN (:names)",
            new MapSqlParameterSource("names", names),
            rs -> {
                ids.put(rs.getString("name"), rs.getInt("id"));
            });
        return ids;
    }

    /** Drop the reservation so a failed upstream does not consume budget. */
    public void settleFailure(Integer logEntryId, String errorMessage) {
        if (logEntryId == null) {
            return;
        }
        String msg = errorMessage == null ? null
            : (errorMessage.length() > 500 ? errorMessage.substring(0, 500) : errorMessage);
        jdbc.update("""
            UPDATE log_entry
               SET timestamp_response = NOW(),
                   result_status = 'error',
                   settled_cost_micro_cents = 0,
                   cost_finalized = TRUE,
                   error_message = :err
             WHERE id = :id
            """, new MapSqlParameterSource()
            .addValue("id", logEntryId)
            .addValue("err", msg));
    }

    /**
     * Zero gateway reservations abandoned after process loss (no response,
     * still in-flight past the stale window).
     */
    public void reconcileStale() {
        jdbc.update("""
            UPDATE log_entry
               SET timestamp_response = NOW(),
                   result_status = 'error',
                   settled_cost_micro_cents = 0,
                   cost_finalized = TRUE,
                   error_message = 'gateway reservation abandoned (stale)'
             WHERE result_status IS NULL
               AND cost_finalized = TRUE
               AND settled_cost_micro_cents IS NOT NULL
               AND settled_cost_micro_cents > 0
               AND request_id LIKE 'gw-%%'
               AND timestamp_response IS NULL
               AND timestamp_request < NOW() - make_interval(mins => :mins)
            """, new MapSqlParameterSource("mins", staleAfterMinutes));
    }
}
