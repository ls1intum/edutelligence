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
 * <p>{@link GatewayBudgetService} sums {@code log_entry_cost}. In-flight rows
 * are not priced, so a reservation must land as a finalized settled cost before
 * the upstream call starts — otherwise concurrent requests can all pass the
 * same check. After the stream ends the reservation is reconciled (kept on
 * success as an approximate charge, zeroed on upstream failure).
 */
@Service
public class GatewayCloudAccounting {

    private final NamedParameterJdbcTemplate jdbc;
    private final GatewayBudgetService budgetService;
    private final long reservationMicroCents;

    public GatewayCloudAccounting(
            NamedParameterJdbcTemplate jdbc,
            GatewayBudgetService budgetService,
            @Value("${logos.gateway.budget-reservation-micro-cents:1000000}") long reservationMicroCents) {
        this.jdbc = jdbc;
        this.budgetService = budgetService;
        this.reservationMicroCents = Math.max(0L, reservationMicroCents);
    }

    /**
     * Insert a budget-visible reservation and invalidate the process-local
     * budget cache so the next admission check sees it.
     *
     * @return log_entry id, or {@code null} when reservation amount is 0
     */
    public Integer reserve(GatewayKey key, GatewayDeployment deployment) {
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
                'success', TRUE, :settled,
                'BILLING'
            )
            """, params, keys, new String[] {"id"});
        Number id = keys.getKey();
        budgetService.invalidateUsageCache(key);
        return id == null ? null : id.intValue();
    }

    /** Keep the reservation as approximate cost and stamp the response time. */
    public void settleSuccess(Integer logEntryId) {
        if (logEntryId == null) {
            return;
        }
        jdbc.update("""
            UPDATE log_entry
               SET timestamp_response = NOW()
             WHERE id = :id
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
}
