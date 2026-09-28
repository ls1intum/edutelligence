package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Budget-visible accounting for the direct-cloud path.
 *
 * <p>{@link #admitAndReserve} checks the budget from the short-TTL snapshot,
 * then inserts an in-flight reservation ({@code result_status IS NULL}) and
 * adds it to this instance's snapshot. Cloud RPM/TPM are enforced separately
 * in Redis ({@link GatewayCloudRateLimiter}) before this method runs. Nothing
 * on this path locks a shared row or touches more than the key's own recent
 * rows: requests on one key run concurrently, across threads and across
 * replicas, and their cost does not grow with the size of the log. The budget
 * is approximate by design — see {@link GatewayBudgetService} for the
 * overshoot bound.
 *
 * <p>{@link #reconcileStale} zeros reservations abandoned after process loss.
 * It sweeps the whole table (bounded by the partial index on in-flight gateway
 * rows), so it runs on a schedule rather than inside a request.
 *
 * <p>On success the reservation is replaced by the real charge: the reported
 * token counts are written to {@code usage_tokens} and the row is un-finalized,
 * which hands pricing to {@code logos_price_usage} through the
 * {@code log_entry_cost} view — the same computation the orchestrator path
 * settles with. Only a response that reports no usage at all keeps the flat
 * reservation, and failure zeros it.
 *
 * <p>The row is written at the key's own logging level, and a key set to
 * {@code FULL} stores its request and response payloads like the orchestrator
 * does. A streamed response has no single body to store, so it records the
 * level without a response payload.
 */
@Service
public class GatewayCloudAccounting {

    /** The only levels {@code logging_enum} has; anything else is not a level we may store. */
    private static final String LEVEL_FULL = "FULL";
    private static final String LEVEL_BILLING = "BILLING";

    private final NamedParameterJdbcTemplate jdbc;
    private final GatewayBudgetService budgetService;
    private final ObjectMapper objectMapper;
    private final long reservationMicroCents;
    private final int staleAfterMinutes;

    public GatewayCloudAccounting(
            NamedParameterJdbcTemplate jdbc,
            GatewayBudgetService budgetService,
            ObjectMapper objectMapper,
            @Value("${logos.gateway.budget-reservation-micro-cents:1000000}") long reservationMicroCents,
            @Value("${logos.gateway.budget-reservation-stale-minutes:30}") int staleAfterMinutes) {
        this.jdbc = jdbc;
        this.budgetService = budgetService;
        this.objectMapper = objectMapper;
        this.reservationMicroCents = Math.max(0L, reservationMicroCents);
        this.staleAfterMinutes = Math.max(1, staleAfterMinutes);
    }

    /**
     * Check budget then insert an in-flight reservation.
     *
     * <p>Deliberately lock-free. A per-key row lock here would serialize every
     * request on that key for the whole admission, on every replica at once;
     * the reservation row is what makes concurrent budget admissions visible
     * to each other, and the insert is atomic on its own. Two requests on the
     * same key that are admitted in the same instant may both pass the budget
     * check — the overshoot that admits is one reservation per such request,
     * the bound the budget already documents. Cloud RPM/TPM are claimed in
     * Redis before this method is called.
     *
     * @param requestBody the forwarded request, stored when the key logs payloads
     * @return log_entry id, or {@code null} when reservation amount is 0
     */
    @Transactional
    public Integer admitAndReserve(GatewayKey key, GatewayDeployment deployment, byte[] requestBody) {
        budgetService.enforceCloudBudget(key);

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
            .addValue("settled", reservationMicroCents)
            .addValue("privacy_level", privacyLevel(key))
            .addValue("input_payload", key.logsFullPayloads() ? asJsonb(requestBody) : null);
        KeyHolder keys = new GeneratedKeyHolder();
        jdbc.update("""
            INSERT INTO log_entry (
                timestamp_request, timestamp_forwarding,
                api_key_id, team_id, user_id, environment,
                model_id, provider_id, request_id,
                result_status, cost_finalized, settled_cost_micro_cents,
                privacy_level, input_payload
            ) VALUES (
                NOW(), NOW(),
                :api_key_id, :team_id, :user_id, :environment,
                :model_id, :provider_id, :request_id,
                NULL, TRUE, :settled,
                CAST(:privacy_level AS logging_enum), CAST(:input_payload AS jsonb)
            )
            """, params, keys, new String[] {"id"});
        Number id = keys.getKey();
        budgetService.noteReservation(key, reservationMicroCents);
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
     * @param usage        canonical token counts, empty when the response reported none
     * @param responseBody the response to store, or {@code null} when the key does
     *                     not log payloads or the response streamed
     * @param serviceTier  the tier the response reported (e.g. {@code flex}),
     *                     or {@code null}; pricing prefers the matching
     *                     {@code token_prices} row for it
     */
    @Transactional
    public void settleSuccess(Integer logEntryId, Map<String, Long> usage,
                              byte[] responseBody, String serviceTier) {
        if (logEntryId == null) {
            return;
        }
        boolean priced = usage != null && !usage.isEmpty();
        // Claim the row first: a reservation already zeroed by reconcileStale
        // (or settled by a racing callback) must not gain usage rows. The tier
        // settles in the same statement the row transitions to success, so
        // log_entry_cost never reads a settled row without the tier its
        // response reported.
        int claimed = jdbc.update(priced ? """
            UPDATE log_entry
               SET timestamp_response = NOW(),
                   result_status = 'success',
                   service_tier = :serviceTier,
                   settled_cost_micro_cents = NULL,
                   cost_finalized = FALSE
             WHERE id = :id
               AND result_status IS NULL
            """ : """
            UPDATE log_entry
               SET timestamp_response = NOW(),
                   result_status = 'success',
                   service_tier = :serviceTier,
                   cost_finalized = TRUE
             WHERE id = :id
               AND result_status IS NULL
            """, new MapSqlParameterSource("id", logEntryId).addValue("serviceTier", serviceTier));
        if (claimed == 0) {
            return;
        }
        storeResponsePayload(logEntryId, responseBody);
        if (priced) {
            upsertUsageTokens(logEntryId, usage);
            restoreReservationIfUnpriced(logEntryId);
        }
    }

    /**
     * Put the reservation back when the stored usage prices to nothing.
     *
     * <p>Reported usage is not the same as billable usage: a deployment with no
     * price rows, or a response that reports only a total, leaves
     * {@code logos_price_usage} with nothing to charge and
     * {@code log_entry_cost} NULL. Releasing the reservation on that row would
     * make a successful request free — the opposite failure to the one this
     * path is here to fix.
     */
    private void restoreReservationIfUnpriced(int logEntryId) {
        if (reservationMicroCents <= 0) {
            return;
        }
        jdbc.update("""
            UPDATE log_entry
               SET settled_cost_micro_cents = :settled,
                   cost_finalized = TRUE
             WHERE id = :id
               AND cost_finalized = FALSE
               AND (SELECT cost_micro_cents FROM log_entry_cost WHERE log_entry_id = :id) IS NULL
            """, new MapSqlParameterSource()
            .addValue("id", logEntryId)
            .addValue("settled", reservationMicroCents));
    }

    /**
     * Store the response body on a row whose key logs payloads.
     *
     * <p>Gated on the stored level rather than the caller's word, so a row can
     * never end up holding a payload its privacy level does not permit.
     */
    private void storeResponsePayload(int logEntryId, byte[] responseBody) {
        String payload = asJsonb(responseBody);
        if (payload == null) {
            return;
        }
        jdbc.update("""
            UPDATE log_entry
               SET response_payload = CAST(:payload AS jsonb)
             WHERE id = :id
               AND privacy_level = 'FULL'
            """, new MapSqlParameterSource()
            .addValue("id", logEntryId)
            .addValue("payload", payload));
    }

    /** The key's logging level, or {@code BILLING} for anything unrecognised. */
    private static String privacyLevel(GatewayKey key) {
        return key != null && key.logsFullPayloads() ? LEVEL_FULL : LEVEL_BILLING;
    }

    /**
     * One JSON document for a {@code jsonb} column, or null when there is none.
     *
     * <p>Re-serialising what was parsed is what makes this safe to cast: a body
     * that is not JSON, or carries bytes {@code jsonb} rejects, yields null
     * instead of failing the request it belongs to.
     */
    private String asJsonb(byte[] body) {
        if (body == null || body.length == 0) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(objectMapper.readTree(body));
        } catch (Exception e) {
            return null;
        }
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
     *
     * <p>Runs on a fixed delay on every replica; the update is idempotent, so
     * replicas sweeping at once only cost each other a no-op. The predicate is
     * the one {@code idx_log_entry_gateway_in_flight} is defined on, which keeps
     * the sweep proportional to the rows still in flight rather than to the
     * table.
     */
    @Scheduled(
        initialDelayString = "${logos.gateway.budget-reservation-reconcile-seconds:60}",
        fixedDelayString = "${logos.gateway.budget-reservation-reconcile-seconds:60}",
        timeUnit = TimeUnit.SECONDS)
    public void reconcileStale() {
        jdbc.update("""
            UPDATE log_entry
               SET timestamp_response = NOW(),
                   result_status = 'error',
                   settled_cost_micro_cents = 0,
                   cost_finalized = TRUE,
                   error_message = 'gateway reservation abandoned (stale)'
             WHERE result_status IS NULL
               AND request_id LIKE 'gw-%'
               AND cost_finalized = TRUE
               AND settled_cost_micro_cents IS NOT NULL
               AND settled_cost_micro_cents > 0
               AND timestamp_response IS NULL
               AND timestamp_request < NOW() - make_interval(mins => :mins)
            """, new MapSqlParameterSource("mins", staleAfterMinutes));
    }
}
