package de.tum.cit.aet.logos.logoswebservice.gateway;

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
 * process loss. Settled success keeps the approximate charge; failure zeros it.
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

    /** Promote the in-flight reservation to a successful approximate charge. */
    public void settleSuccess(Integer logEntryId) {
        if (logEntryId == null) {
            return;
        }
        jdbc.update("""
            UPDATE log_entry
               SET timestamp_response = NOW(),
                   result_status = 'success',
                   cost_finalized = TRUE
             WHERE id = :id
               AND result_status IS NULL
            """, new MapSqlParameterSource("id", logEntryId));
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
