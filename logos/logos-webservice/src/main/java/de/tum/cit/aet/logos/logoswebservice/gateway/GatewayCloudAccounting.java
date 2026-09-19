package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;

/**
 * Budget-visible accounting for the direct-cloud path.
 *
 * <p>{@link GatewayBudgetService} sums {@code log_entry_cost} plus in-flight
 * gateway reservations ({@code result_status IS NULL}, {@code cost_finalized},
 * non-null {@code settled_cost_micro_cents}). Reservations start in-flight so a
 * crashed replica does not permanently charge success; {@link #reconcileStale}
 * zeros abandoned rows. After the stream ends the reservation is reconciled
 * (kept on success as an approximate charge, zeroed on upstream failure).
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
     * Insert a budget-visible in-flight reservation and invalidate the
     * process-local budget cache so the next admission check sees it.
     *
     * @return log_entry id, or {@code null} when reservation amount is 0
     */
    public Integer reserve(GatewayKey key, GatewayDeployment deployment) {
        if (reservationMicroCents <= 0) {
            return null;
        }
        reconcileStale();
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
