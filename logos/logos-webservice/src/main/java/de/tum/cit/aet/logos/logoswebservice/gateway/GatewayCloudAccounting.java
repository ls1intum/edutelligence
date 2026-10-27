package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Budget-visible accounting for the direct-cloud path.
 *
 * <p>{@link #admitAndReserve} checks the budget from the short-TTL snapshot,
 * then inserts an in-flight reservation ({@code result_status IS NULL}) and
 * after commit adds it to this instance's snapshot. Cloud RPM/TPM are enforced
 * separately in Redis ({@link GatewayCloudRateLimiter}) before this method runs.
 * Nothing on this path locks a shared row or touches more than the key's own
 * recent rows: requests on one key run concurrently, across threads and across
 * replicas, and their cost does not grow with the size of the log. The budget
 * is approximate by design — see {@link GatewayBudgetService} for the
 * overshoot bound.
 *
 * <p>{@link #reconcileStale} zeros reservations abandoned after process loss.
 * It sweeps the whole table (bounded by the partial index on in-flight gateway
 * rows), so it runs on a schedule rather than inside a request.
 *
 * <p>On success the reservation is replaced by the real charge: the reported
 * token counts are written to {@code usage_tokens}, priced once with
 * {@code logos_price_usage} — the same computation the orchestrator path
 * settles with — and the price is stored on the row with
 * {@code cost_finalized = TRUE}. A row left un-finalized would be re-priced by
 * the {@code log_entry_cost} view on every read, and every budget refresh
 * reads the key's whole month, so admission would slow down with every
 * request the key makes. Only a response that reports no usage at all, or
 * usage that prices to nothing, keeps the flat reservation, and failure
 * zeros it.
 *
 * <p>{@link #finalizeUnsettled} finalizes successful rows that still carry no
 * stored price, in bounded batches on a schedule.
 *
 * <p>The row is written at the effective logging level for the request (the
 * key's configured level, or a per-request {@code logos-logging} override).
 * {@code FULL} stores request and response payloads like the orchestrator
 * does. A streamed response has no single body to store, so it records the
 * level without a response payload.
 */
@Service
public class GatewayCloudAccounting {

    /**
     * Freeze the price of settled successes: the token usage priced by
     * {@code logos_price_usage}, or the reservation when it prices to nothing.
     * Spelled like the orchestrator's settled-cost snapshot so both paths store
     * the same figure the {@code log_entry_cost} view would compute live; a
     * later price change does not rewrite completed budget history.
     * {@code %s} selects the rows.
     */
    private static final String SETTLED_COST_SNAPSHOT_SQL = """
        UPDATE log_entry le
           SET settled_cost_micro_cents = COALESCE(
                   logos_price_usage(
                       le.model_id, le.provider_id,
                       COALESCE(le.timestamp_response, le.timestamp_request),
                       le.service_tier,
                       (SELECT jsonb_object_agg(tt.name, ut.token_count)
                          FROM usage_tokens ut
                          JOIN token_types tt ON tt.id = ut.type_id
                         WHERE ut.log_entry_id = le.id)),
                   CAST(:reservation AS BIGINT)),
               cost_finalized = TRUE
         WHERE le.result_status = 'success'
           AND le.cost_finalized = FALSE
           AND %s
        """;

    private static final Logger log = LoggerFactory.getLogger(GatewayCloudAccounting.class);

    /**
     * The provider-window columns a settle writes. A timing the forward did
     * not reach stays as it was (NULL on a fresh reservation), and the
     * statistics fall back to the forwarding/response split for it.
     */
    private static final String TIMINGS_SET = """
        timestamp_provider_call = COALESCE(CAST(:providerCall AS timestamptz), timestamp_provider_call),
                   time_at_first_token = COALESCE(CAST(:firstToken AS timestamptz), time_at_first_token),
                   timestamp_provider_response = COALESCE(CAST(:providerResponse AS timestamptz),
                                                          timestamp_provider_response)""";

    /** The only levels {@code logging_enum} has; anything else is not a level we may store. */
    private static final String LEVEL_FULL = GatewayLoggingLevel.LEVEL_FULL;
    private static final String LEVEL_BILLING = GatewayLoggingLevel.LEVEL_BILLING;

    private final NamedParameterJdbcTemplate jdbc;
    private final GatewayBudgetService budgetService;
    private final ObjectMapper objectMapper;
    private final long reservationMicroCents;
    private final int staleAfterMinutes;
    private final int finalizeBatchSize;
    private final int finalizeMaxBatches;

    public GatewayCloudAccounting(
            NamedParameterJdbcTemplate jdbc,
            GatewayBudgetService budgetService,
            ObjectMapper objectMapper,
            @Value("${logos.gateway.budget-reservation-micro-cents:1000000}") long reservationMicroCents,
            @Value("${logos.gateway.budget-reservation-stale-minutes:30}") int staleAfterMinutes,
            @Value("${logos.gateway.cost-finalize-batch-size:1000}") int finalizeBatchSize,
            @Value("${logos.gateway.cost-finalize-max-batches:50}") int finalizeMaxBatches) {
        this.jdbc = jdbc;
        this.budgetService = budgetService;
        this.objectMapper = objectMapper;
        this.reservationMicroCents = Math.max(0L, reservationMicroCents);
        this.staleAfterMinutes = Math.max(1, staleAfterMinutes);
        this.finalizeBatchSize = Math.max(1, finalizeBatchSize);
        this.finalizeMaxBatches = Math.max(1, finalizeMaxBatches);
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
     * @param requestBody the forwarded request, stored when the effective level is FULL
     * @return log_entry id, or {@code null} when reservation amount is 0
     */
    @Transactional
    public Integer admitAndReserve(GatewayKey key, GatewayDeployment deployment, byte[] requestBody) {
        return admitAndReserve(key, deployment, requestBody,
            GatewayLoggingLevel.resolve(null, key != null ? key.logLevel() : null));
    }

    /**
     * Check budget then insert an in-flight reservation at a resolved logging level.
     *
     * @param logLevel the effective request logging level ({@code FULL} or {@code BILLING})
     * @return log_entry id, or {@code null} when reservation amount is 0
     */
    @Transactional
    public Integer admitAndReserve(GatewayKey key, GatewayDeployment deployment,
                                   byte[] requestBody, String logLevel) {
        return admitAndReserve(key, deployment, requestBody, logLevel, null);
    }

    /**
     * Check budget then insert an in-flight reservation, dated from when the
     * request arrived.
     *
     * <p>The row's {@code timestamp_request} is the arrival instant, its
     * {@code timestamp_forwarding} the moment admission ended. Everything the
     * request waited for in between — the key lookup, the rate limit, the
     * budget check, a free database connection — then shows up in the queue
     * figure the statistics page reads, instead of vanishing before the row
     * exists.
     *
     * @param logLevel  the effective request logging level ({@code FULL} or {@code BILLING})
     * @param arrivedAt when the request reached the gateway; null dates it at admission
     * @return log_entry id, or {@code null} when reservation amount is 0
     */
    @Transactional
    public Integer admitAndReserve(GatewayKey key, GatewayDeployment deployment,
                                   byte[] requestBody, String logLevel, Instant arrivedAt) {
        return admitAndReserve(key, deployment, requestBody, logLevel, arrivedAt, null);
    }

    /**
     * As {@link #admitAndReserve(GatewayKey, GatewayDeployment, byte[], String, Instant)},
     * also storing the reasoning effort the request is forwarded with.
     *
     * @param reasoningEffort the effort in the forwarded body, lower-cased; null when it carries none
     */
    @Transactional
    public Integer admitAndReserve(GatewayKey key, GatewayDeployment deployment,
                                   byte[] requestBody, String logLevel, Instant arrivedAt,
                                   String reasoningEffort) {
        budgetService.enforceCloudBudget(key, deployment.providerId());

        if (reservationMicroCents <= 0) {
            return null;
        }
        String privacy = privacyLevel(logLevel);
        String requestId = "gw-" + UUID.randomUUID();
        Instant admittedAt = Instant.now();
        MapSqlParameterSource params = new MapSqlParameterSource()
            .addValue("arrived", utc(arrivedAt != null && arrivedAt.isBefore(admittedAt) ? arrivedAt : admittedAt))
            .addValue("admitted", utc(admittedAt))
            .addValue("request_id", requestId)
            .addValue("api_key_id", key.id())
            .addValue("team_id", key.teamId())
            .addValue("user_id", key.userId())
            .addValue("environment", key.environment())
            .addValue("model_id", deployment.modelId())
            .addValue("provider_id", deployment.providerId())
            .addValue("settled", reservationMicroCents)
            .addValue("privacy_level", privacy)
            .addValue("reasoning_effort", reasoningEffort)
            .addValue("input_payload",
                GatewayLoggingLevel.storesPayloads(privacy) ? asJsonb(requestBody) : null);
        KeyHolder keys = new GeneratedKeyHolder();
        jdbc.update("""
            INSERT INTO log_entry (
                timestamp_request, timestamp_forwarding,
                api_key_id, team_id, user_id, environment,
                model_id, provider_id, request_id,
                result_status, cost_finalized, settled_cost_micro_cents,
                privacy_level, input_payload, reasoning_effort
            ) VALUES (
                :arrived, :admitted,
                :api_key_id, :team_id, :user_id, :environment,
                :model_id, :provider_id, :request_id,
                NULL, TRUE, :settled,
                CAST(:privacy_level AS logging_enum), CAST(:input_payload AS jsonb),
                CAST(:reasoning_effort AS TEXT)
            )
            """, params, keys, new String[] {"id"});
        Number id = keys.getKey();
        // Bump the snapshot only after commit so a concurrent refresh cannot
        // SELECT before the row is visible and then overwrite the bump.
        noteReservationAfterCommit(key, reservationMicroCents, deployment.providerId());
        return id == null ? null : id.intValue();
    }

    private void noteReservationAfterCommit(GatewayKey key, long microCents, Integer providerId) {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    budgetService.noteReservation(key, microCents, providerId);
                }
            });
        } else {
            budgetService.noteReservation(key, microCents, providerId);
        }
    }

    /**
     * Settle the in-flight reservation as a success.
     *
     * <p>With usage reported, the token counts are stored and priced once by
     * {@code logos_price_usage}, and that price replaces the reservation as
     * the row's finalized cost. Without usage — a streaming upstream that
     * ignored {@code include_usage}, a body past the capture cap — or with
     * usage that prices to nothing, the flat reservation stands, because an
     * unpriced success must not read as free budget.
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
        settleSuccess(logEntryId, usage, responseBody, serviceTier, GatewayForwardTimings.NONE);
    }

    /**
     * Settle the in-flight reservation as a success, with the instants the
     * forward passed through.
     *
     * <p>The timings fill {@code timestamp_provider_call},
     * {@code time_at_first_token} and {@code timestamp_provider_response}, so a
     * cloud row splits into Logos-side wait and provider time like an
     * orchestrator row, and carries a time to first token.
     *
     * @param timings when the upstream was called, answered first and finished
     */
    @Transactional
    public void settleSuccess(Integer logEntryId, Map<String, Long> usage,
                              byte[] responseBody, String serviceTier, GatewayForwardTimings timings) {
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
               SET timestamp_response = :responded,
                   %s,
                   result_status = 'success',
                   service_tier = :serviceTier,
                   settled_cost_micro_cents = NULL,
                   cost_finalized = FALSE
             WHERE id = :id
               AND result_status IS NULL
            """.formatted(TIMINGS_SET) : """
            UPDATE log_entry
               SET timestamp_response = :responded,
                   %s,
                   result_status = 'success',
                   service_tier = :serviceTier,
                   cost_finalized = TRUE
             WHERE id = :id
               AND result_status IS NULL
            """.formatted(TIMINGS_SET),
            timingParams(timings).addValue("id", logEntryId).addValue("serviceTier", serviceTier));
        if (claimed == 0) {
            return;
        }
        storeResponsePayload(logEntryId, responseBody);
        if (priced) {
            upsertUsageTokens(logEntryId, usage);
            jdbc.update(SETTLED_COST_SNAPSHOT_SQL.formatted("le.id = :id"),
                snapshotParams().addValue("id", logEntryId));
        }
    }

    /**
     * Store the price of successful direct-cloud rows that settled without one.
     *
     * <p>{@link #settleSuccess} finalizes its row in the same transaction, so
     * this only finds rows written before it did, or by a settle that did not
     * get that far. Each batch is its own statement, so a long backlog never
     * holds one connection or one set of row locks for the whole sweep, and
     * {@code SKIP LOCKED} lets replicas sweep at once without waiting on each
     * other or on a settle in progress. The batch is collected with
     * {@code ARRAY(...)}, which runs once; a plain {@code IN (SELECT ...
     * LIMIT)} may be re-run by the planner and lock more rows than the limit.
     * The predicate is the one
     * {@code idx_log_entry_gateway_unfinalized} is defined on, which keeps the
     * sweep proportional to the rows still unpriced rather than to the table.
     *
     * <p>Reported usage is not the same as billable usage: a deployment with no
     * price rows, or a response that reports only a total, leaves
     * {@code logos_price_usage} with nothing to charge. Such a row keeps the
     * reservation — releasing it would make a successful request free.
     *
     * @return number of rows finalized
     */
    @Scheduled(
        initialDelayString = "${logos.gateway.cost-finalize-seconds:60}",
        fixedDelayString = "${logos.gateway.cost-finalize-seconds:60}",
        timeUnit = TimeUnit.SECONDS)
    public int finalizeUnsettled() {
        int total = 0;
        for (int batch = 0; batch < finalizeMaxBatches; batch++) {
            int updated = jdbc.update(SETTLED_COST_SNAPSHOT_SQL.formatted("""
                le.id = ANY(ARRAY(
                    SELECT id FROM log_entry
                     WHERE result_status = 'success'
                       AND cost_finalized = FALSE
                       AND request_id LIKE 'gw-%'
                     ORDER BY id
                     LIMIT :limit
                       FOR UPDATE SKIP LOCKED))
                """), snapshotParams().addValue("limit", finalizeBatchSize));
            total += updated;
            if (updated < finalizeBatchSize) {
                break;
            }
        }
        return total;
    }

    /** The reservation an unpriced success keeps; NULL when reservations are off. */
    private MapSqlParameterSource snapshotParams() {
        return new MapSqlParameterSource("reservation",
            reservationMicroCents > 0 ? reservationMicroCents : null);
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

    /**
     * Bind the forward's instants. Every stamp on a gateway row comes from this
     * process's clock — arrival, admission, the provider window and the end —
     * so the intervals between them never mix two clocks.
     */
    private static MapSqlParameterSource timingParams(GatewayForwardTimings timings) {
        GatewayForwardTimings t = timings == null ? GatewayForwardTimings.NONE : timings;
        return new MapSqlParameterSource()
            .addValue("responded", utc(Instant.now()))
            .addValue("providerCall", utc(t.providerCall()))
            .addValue("firstToken", utc(t.firstToken()))
            .addValue("providerResponse", utc(t.providerResponse()));
    }

    /**
     * The instant as a UTC timestamp at the column's precision. The JVM clock
     * can carry nanoseconds, which the JDBC driver would round to microseconds;
     * truncating here keeps every stored timestamp at or before the instant it
     * stands for, so the intervals between them never come out negative.
     */
    private static OffsetDateTime utc(Instant instant) {
        return instant == null ? null : instant.truncatedTo(ChronoUnit.MICROS).atOffset(ZoneOffset.UTC);
    }

    /** Normalise a resolved level to a value {@code logging_enum} accepts. */
    private static String privacyLevel(String logLevel) {
        return GatewayLoggingLevel.storesPayloads(logLevel) ? LEVEL_FULL : LEVEL_BILLING;
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

    /**
     * Record a request the gateway turned away before forwarding it (rate
     * limit, budget, or an unexpected failure in admission), so it shows up in
     * the request log and the stats like any other failed request.
     *
     * <p>The row is already settled: no reservation, no cost. A limiter
     * rejection also sets {@code rate_limit_admitted = FALSE} so the key's
     * window usage does not count it, exactly as on the orchestrator path; any
     * other rejection leaves it NULL, because the limiter did not decide it. The
     * request payload is not stored — a rejected request was never processed. A
     * failure to write the row must not replace the error the caller is about
     * to receive.
     *
     * @param rateLimited whether the cloud RPM/TPM limiter made the rejection
     */
    public void recordRejected(GatewayKey key, GatewayDeployment deployment,
                               String logLevel, String message, boolean rateLimited) {
        String msg = message == null ? null
            : (message.length() > 500 ? message.substring(0, 500) : message);
        try {
            jdbc.update("""
                INSERT INTO log_entry (
                    timestamp_request, timestamp_response,
                    api_key_id, team_id, user_id, environment,
                    model_id, provider_id, request_id,
                    result_status, error_message, rate_limit_admitted,
                    cost_finalized, settled_cost_micro_cents, privacy_level
                ) VALUES (
                    NOW(), NOW(),
                    :api_key_id, :team_id, :user_id, :environment,
                    :model_id, :provider_id, :request_id,
                    'error', :error_message, :rate_limit_admitted,
                    TRUE, 0, CAST(:privacy_level AS logging_enum)
                )
                """, new MapSqlParameterSource()
                .addValue("api_key_id", key.id())
                .addValue("team_id", key.teamId())
                .addValue("user_id", key.userId())
                .addValue("environment", key.environment())
                .addValue("model_id", deployment.modelId())
                .addValue("provider_id", deployment.providerId())
                .addValue("request_id", "gw-" + UUID.randomUUID())
                .addValue("error_message", msg)
                .addValue("rate_limit_admitted", rateLimited ? Boolean.FALSE : null)
                .addValue("privacy_level", privacyLevel(logLevel)));
        } catch (RuntimeException e) {
            log.warn("Could not record rejected request keyId={}", key.id(), e);
        }
    }

    /** Drop the reservation so a failed upstream does not consume budget. */
    public void settleFailure(Integer logEntryId, String errorMessage) {
        settleFailure(logEntryId, errorMessage, GatewayForwardTimings.NONE);
    }

    /**
     * Drop the reservation so a failed upstream does not consume budget, and
     * keep the instants the forward reached so the failure's provider time is
     * not read as Logos-side wait.
     */
    public void settleFailure(Integer logEntryId, String errorMessage, GatewayForwardTimings timings) {
        if (logEntryId == null) {
            return;
        }
        String msg = errorMessage == null ? null
            : (errorMessage.length() > 500 ? errorMessage.substring(0, 500) : errorMessage);
        jdbc.update("""
            UPDATE log_entry
               SET timestamp_response = :responded,
                   %s,
                   result_status = 'error',
                   settled_cost_micro_cents = 0,
                   cost_finalized = TRUE,
                   error_message = :err
             WHERE id = :id
            """.formatted(TIMINGS_SET), timingParams(timings)
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
