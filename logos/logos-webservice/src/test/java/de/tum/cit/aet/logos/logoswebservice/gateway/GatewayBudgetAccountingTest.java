package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Clock;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.web.server.ResponseStatusException;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/**
 * What the budget check counts for direct-cloud traffic.
 *
 * <p>A settled gateway request is priced from its tokens like any other, so it
 * must reach the budget through {@code log_entry_cost} — counted once, at what
 * it actually cost. Only a request still in flight has no price yet, and its
 * reservation is what holds the budget until it settles.
 */
@SpringBootTest
@Testcontainers
class GatewayBudgetAccountingTest {

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    NamedParameterJdbcTemplate namedJdbc;

    @Autowired
    GatewayCloudAccounting accounting;

    @MockitoBean
    JwtDecoder jwtDecoder;

    @Container
    @SuppressWarnings("resource")
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17")
            .withDatabaseName("logosdb")
            .withUsername("postgres")
            .withPassword("root");

    @DynamicPropertySource
    @SuppressWarnings("unused")
    static void configureProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
        registry.add("spring.datasource.driver-class-name", () -> "org.postgresql.Driver");
        registry.add("spring.liquibase.enabled", () -> "true");
        registry.add("spring.liquibase.change-log", () -> "classpath:liquibase/changelog/master.xml");
        registry.add("spring.jpa.hibernate.ddl-auto", () -> "validate");
    }

    private static final AtomicInteger SEQ = new AtomicInteger(1);
    private static final long RESERVATION = 1_000_000L;

    /** Cost of the usage seeded below: 1000 in at 20000/k + 300 out at 120000/k. */
    private static final long REAL_COST = 20_000L + 36_000L;

    private static final Map<String, Long> USAGE =
        Map.of("prompt_tokens", 1000L, "completion_tokens", 300L);

    private static final byte[] REQUEST_BODY =
        "{\"model\":\"m\",\"messages\":[]}".getBytes(java.nio.charset.StandardCharsets.UTF_8);

    /** No TTL: every check reads the database, so a test never asserts a stale snapshot. */
    private GatewayBudgetService uncachedBudgetService() {
        return new GatewayBudgetService(namedJdbc, 0, Clock.systemUTC());
    }

    // ------------------------------------------------- what a settled call costs

    @Test
    void settledCloudRequest_countsWhatItCostNotTheReservation() {
        Fixture f = seedFixture(ApiKeyType.application);
        setKeyBudget(f.apiKeyId(), 500_000L);
        accounting.settleSuccess(admit(f), USAGE, null);

        // 56_000 spent against a 500_000 limit leaves room; had the flat
        // reservation been counted, 1_000_000 would already be over it.
        assertThatCode(() -> uncachedBudgetService().enforceCloudBudget(f.key()))
            .doesNotThrowAnyException();
    }

    @Test
    void settledCloudRequest_isCountedExactlyOnce() {
        Fixture f = seedFixture(ApiKeyType.application);
        accounting.settleSuccess(admit(f), USAGE, null);

        // A limit just above one charge admits; just below it rejects. Double
        // counting would reject at both.
        setKeyBudget(f.apiKeyId(), REAL_COST + 1);
        assertThatCode(() -> uncachedBudgetService().enforceCloudBudget(f.key()))
            .doesNotThrowAnyException();
        setKeyBudget(f.apiKeyId(), REAL_COST);
        assertBudgetRejects(f);
    }

    @Test
    void spendAccumulatesAcrossSettledRequests() {
        Fixture f = seedFixture(ApiKeyType.application);
        accounting.settleSuccess(admit(f), USAGE, null);
        accounting.settleSuccess(admit(f), USAGE, null);

        setKeyBudget(f.apiKeyId(), 2 * REAL_COST + 1);
        assertThatCode(() -> uncachedBudgetService().enforceCloudBudget(f.key()))
            .doesNotThrowAnyException();
        setKeyBudget(f.apiKeyId(), 2 * REAL_COST);
        assertBudgetRejects(f);
    }

    // ------------------------------------------------------- in-flight and failure

    @Test
    void inFlightReservationHoldsTheBudgetUntilItSettles() {
        Fixture f = seedFixture(ApiKeyType.application);
        setKeyBudget(f.apiKeyId(), RESERVATION);
        int logId = admit(f);

        // Nothing is priced yet, so the reservation is the only thing standing
        // between a concurrent request and an overspend.
        assertBudgetRejects(f);

        accounting.settleSuccess(logId, USAGE, null);
        assertThatCode(() -> uncachedBudgetService().enforceCloudBudget(f.key()))
            .doesNotThrowAnyException();
    }

    @Test
    void failedRequestFreesTheBudgetItReserved() {
        Fixture f = seedFixture(ApiKeyType.application);
        setKeyBudget(f.apiKeyId(), RESERVATION);
        int logId = admit(f);

        accounting.settleFailure(logId, "Upstream HTTP 500");

        assertThatCode(() -> uncachedBudgetService().enforceCloudBudget(f.key()))
            .doesNotThrowAnyException();
    }

    @Test
    void successWithoutUsage_stillCountsItsReservation() {
        // An unpriced success must not read as free budget.
        Fixture f = seedFixture(ApiKeyType.application);
        setKeyBudget(f.apiKeyId(), RESERVATION);

        accounting.settleSuccess(admit(f), Map.of(), null);

        assertBudgetRejects(f);
    }

    @Test
    void reservationStopsCountingOnceReconciledAsStale() {
        Fixture f = seedFixture(ApiKeyType.application);
        setKeyBudget(f.apiKeyId(), RESERVATION);
        int logId = admit(f);
        jdbc.update("UPDATE log_entry SET timestamp_request = NOW() - INTERVAL '2 hours' WHERE id = ?", logId);

        accounting.reconcileStale();

        assertThatCode(() -> uncachedBudgetService().enforceCloudBudget(f.key()))
            .doesNotThrowAnyException();
    }

    // ------------------------------------------------------------- team budget

    @Test
    void teamBudgetCountsSettledCloudSpendOfItsDeveloperKeys() {
        Fixture f = seedFixture(ApiKeyType.developer);
        accounting.settleSuccess(admit(f), USAGE, null);

        setTeamBudget(f.teamId(), REAL_COST + 1);
        assertThatCode(() -> uncachedBudgetService().enforceCloudBudget(f.key()))
            .doesNotThrowAnyException();
        setTeamBudget(f.teamId(), REAL_COST);
        assertThatThrownBy(() -> uncachedBudgetService().enforceCloudBudget(f.key()))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("Team monthly budget exceeded");
    }

    // ------------------------------------------------------- orchestrator path

    @Test
    void orchestratorSpendStillCounts() {
        // The gateway's own rows are no longer excluded from log_entry_cost;
        // the requests it proxies must keep counting as they always did.
        Fixture f = seedFixture(ApiKeyType.application);
        int logId = jdbc.queryForObject(
            "INSERT INTO log_entry (timestamp_request, api_key_id, model_id, provider_id, result_status, request_id) "
            + "VALUES (NOW(), ?, ?, ?, 'success'::result_status_enum, ?) RETURNING id",
            Integer.class, f.apiKeyId(), f.modelId(), f.providerId(), "orch-" + SEQ.getAndIncrement());
        seedUsageToken(logId, "prompt_tokens", 1000);
        seedUsageToken(logId, "completion_tokens", 300);

        setKeyBudget(f.apiKeyId(), REAL_COST + 1);
        assertThatCode(() -> uncachedBudgetService().enforceCloudBudget(f.key()))
            .doesNotThrowAnyException();
        setKeyBudget(f.apiKeyId(), REAL_COST);
        assertBudgetRejects(f);
    }

    // --------------------------------------------------------------- helpers

    private record Fixture(int modelId, int providerId, int teamId, int apiKeyId,
                           GatewayKey key, GatewayDeployment deployment) {
    }

    private int admit(Fixture f) {
        Integer id = accounting.admitAndReserve(f.key(), f.deployment(), null, REQUEST_BODY);
        assertThat(id).isNotNull();
        return id;
    }

    private void assertBudgetRejects(Fixture f) {
        assertThatThrownBy(() -> uncachedBudgetService().enforceCloudBudget(f.key()))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(e -> assertThat(((ResponseStatusException) e).getStatusCode())
                .isEqualTo(HttpStatus.PAYMENT_REQUIRED));
    }

    private void setKeyBudget(int apiKeyId, long microCents) {
        jdbc.update("UPDATE api_keys SET settings = jsonb_build_object('budget_limit_micro_cents', ?::bigint) "
            + "WHERE id = ?", microCents, apiKeyId);
    }

    private void setTeamBudget(int teamId, long microCents) {
        jdbc.update("UPDATE teams SET team_monthly_budget_micro_cents = ? WHERE id = ?", microCents, teamId);
    }

    private Fixture seedFixture(ApiKeyType keyType) {
        return seedFixture(keyType, "BILLING");
    }

    private Fixture seedFixture(ApiKeyType keyType, String logLevel) {
        int modelId = jdbc.queryForObject(
            "INSERT INTO models (name) VALUES (?) RETURNING id",
            Integer.class, "m-" + SEQ.getAndIncrement());
        int providerId = jdbc.queryForObject(
            "INSERT INTO providers (name, base_url, provider_type, cloud_provider_type, auth_name, auth_format) "
            + "VALUES (?, 'http://x', 'cloud', 'openai'::cloud_provider_type_enum, 'Authorization', 'Bearer %s') "
            + "RETURNING id",
            Integer.class, "p-" + SEQ.getAndIncrement());
        seedPrice(modelId, providerId, "billed_input_uncached", 20000);
        seedPrice(modelId, providerId, "billed_output_text", 120000);

        // A high team default keeps the personal limit out of the way until a
        // test sets one deliberately.
        int teamId = jdbc.queryForObject(
            "INSERT INTO teams (name, default_monthly_budget_micro_cents, team_monthly_budget_micro_cents) "
            + "VALUES (?, 1000000000, 1000000000) RETURNING id",
            Integer.class, "t-" + SEQ.getAndIncrement());
        int apiKeyId = jdbc.queryForObject(
            "INSERT INTO api_keys (key_value, name, team_id, key_type, log) "
            + "VALUES (?, ?, ?, ?::api_key_type_enum, ?::logging_enum) RETURNING id",
            Integer.class, "lg-" + SEQ.getAndIncrement(), "k-" + SEQ.get(), teamId,
            keyType.name(), logLevel);

        GatewayKey key = new GatewayKey(apiKeyId, "lg-x", "k", keyType,
            teamId, null, "test", false, null, 0, logLevel);
        GatewayDeployment deployment = new GatewayDeployment(modelId, "m", providerId, "p",
            "cloud", "openai", "http://x", "/v1/chat/completions",
            "Authorization", "Bearer %s", "sk-x", "BILLING", null);
        return new Fixture(modelId, providerId, teamId, apiKeyId, key, deployment);
    }

    private void seedPrice(int modelId, int providerId, String typeName, long pricePerKUnit) {
        jdbc.update("INSERT INTO token_types (name) VALUES (?) ON CONFLICT (name) DO NOTHING", typeName);
        jdbc.update(
            "INSERT INTO token_prices (type_id, model_id, provider_id, unit, min_context_tokens, "
            + "service_tier, valid_from, price_per_k_unit) VALUES "
            + "((SELECT id FROM token_types WHERE name = ?), ?, ?, 'token', 0, 'default', "
            + "'2020-01-01T00:00:00Z'::timestamptz, ?)",
            typeName, modelId, providerId, pricePerKUnit);
    }

    private void seedUsageToken(int logEntryId, String typeName, long count) {
        jdbc.update("INSERT INTO token_types (name) VALUES (?) ON CONFLICT (name) DO NOTHING", typeName);
        jdbc.update("INSERT INTO usage_tokens (type_id, log_entry_id, token_count) "
            + "VALUES ((SELECT id FROM token_types WHERE name = ?), ?, ?)", typeName, logEntryId, count);
    }
}
