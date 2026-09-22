package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/**
 * Settlement of the direct-cloud path: a reservation admits the request, and
 * the reported token usage is what the request is finally billed at — the flat
 * reservation only stands for a response that reported no usage at all.
 */
@SpringBootTest
@Testcontainers
class GatewayCloudAccountingTest {

    @Autowired
    JdbcTemplate jdbc;

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

    /** Default reservation: 1_000_000 micro-cents, i.e. one cent. */
    private static final long RESERVATION = 1_000_000L;

    // ------------------------------------------------------------- settlement

    @Test
    void settleSuccess_billsTheReportedTokensInsteadOfTheReservation() {
        Fixture f = seedPricedDeployment();
        int logId = admit(f);
        assertThat(settledCost(logId)).isEqualTo(RESERVATION);

        accounting.settleSuccess(logId, Map.of(
            "prompt_tokens", 1000L, "completion_tokens", 300L, "total_tokens", 1300L));

        // 1000 * 20000/1000 + 300 * 120000/1000 — the same computation the
        // orchestrator path settles with, not the flat reservation.
        assertThat(cost(logId)).isEqualTo(20_000L + 36_000L);
        assertThat(cost(logId)).isNotEqualTo(RESERVATION);
        assertThat(usageTokens(logId)).containsExactlyInAnyOrderEntriesOf(Map.of(
            "prompt_tokens", 1000, "completion_tokens", 300, "total_tokens", 1300));
        assertThat(status(logId)).isEqualTo("success");
    }

    @Test
    void settleSuccess_cachedPromptTokensAreBilledAtTheCacheRate() {
        Fixture f = seedPricedDeployment();
        jdbc.update("INSERT INTO token_prices (type_id, model_id, provider_id, unit, min_context_tokens, "
            + "service_tier, valid_from, price_per_k_unit) VALUES "
            + "((SELECT id FROM token_types WHERE name = 'billed_input_cache_read'), ?, ?, 'token', 0, "
            + "'default', '2020-01-01T00:00:00Z'::timestamptz, 2000)", f.modelId(), f.providerId());
        int logId = admit(f);

        accounting.settleSuccess(logId, Map.of(
            "prompt_tokens", 1000L, "prompt_cached_tokens", 800L, "completion_tokens", 300L));

        // 200 uncached at 20000 + 800 cached at 2000 + 300 output at 120000.
        assertThat(cost(logId)).isEqualTo(4_000L + 1_600L + 36_000L);
    }

    @Test
    void settleSuccess_withoutUsage_keepsTheReservation() {
        // An unpriced success must not read as free budget.
        Fixture f = seedPricedDeployment();
        int logId = admit(f);

        accounting.settleSuccess(logId, Map.of());

        assertThat(settledCost(logId)).isEqualTo(RESERVATION);
        assertThat(cost(logId)).isEqualTo(RESERVATION);
        assertThat(usageTokens(logId)).isEmpty();
        assertThat(status(logId)).isEqualTo("success");
    }

    @Test
    void settleSuccess_isIdempotentAcrossRetries() {
        Fixture f = seedPricedDeployment();
        int logId = admit(f);

        accounting.settleSuccess(logId, Map.of("prompt_tokens", 100L));
        Long afterFirst = cost(logId);
        accounting.settleSuccess(logId, Map.of("prompt_tokens", 999L));

        // The row is claimed once; a repeat settle cannot re-bill it.
        assertThat(cost(logId)).isEqualTo(afterFirst);
        assertThat(usageTokens(logId)).containsExactlyInAnyOrderEntriesOf(Map.of("prompt_tokens", 100));
    }

    @Test
    void settleSuccess_afterStaleReconcileLeavesTheZeroedRowAlone() {
        Fixture f = seedPricedDeployment();
        int logId = admit(f);
        jdbc.update("UPDATE log_entry SET timestamp_request = NOW() - INTERVAL '2 hours' WHERE id = ?", logId);
        accounting.reconcileStale();

        accounting.settleSuccess(logId, Map.of("prompt_tokens", 500L));

        assertThat(status(logId)).isEqualTo("error");
        assertThat(settledCost(logId)).isZero();
        assertThat(usageTokens(logId)).isEmpty();
    }

    @Test
    void settleFailure_zerosTheReservation() {
        Fixture f = seedPricedDeployment();
        int logId = admit(f);

        accounting.settleFailure(logId, "Upstream HTTP 500");

        assertThat(cost(logId)).isZero();
        assertThat(status(logId)).isEqualTo("error");
    }

    @Test
    void settleSuccess_registersATokenTypeTheDeploymentHasNotReportedBefore() {
        Fixture f = seedPricedDeployment();
        int logId = admit(f);

        accounting.settleSuccess(logId, Map.of("prompt_tokens", 100L, "citation_tokens", 7L));

        assertThat(usageTokens(logId)).containsEntry("citation_tokens", 7);
    }

    // ------------------------------------------------------------- in-flight

    @Test
    void inFlightReservationIsNotPricedButStillCountsAgainstBudget() {
        Fixture f = seedPricedDeployment();
        int logId = admit(f);

        // log_entry_cost prices settled requests only; the reservation is what
        // holds the budget while the upstream call is running.
        assertThat(cost(logId)).isNull();
        assertThat(settledCost(logId)).isEqualTo(RESERVATION);
        assertThat(status(logId)).isNull();
    }

    // --------------------------------------------------------------- helpers

    private record Fixture(int modelId, int providerId, GatewayKey key, GatewayDeployment deployment) {
    }

    private int admit(Fixture f) {
        Integer id = accounting.admitAndReserve(f.key(), f.deployment(), null);
        assertThat(id).isNotNull();
        return id;
    }

    /**
     * A cloud deployment priced per token, with an API key that can reach it.
     * Prices match {@code TokenCostFunctionTest} so the expected figures read
     * the same in both places.
     */
    private Fixture seedPricedDeployment() {
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

        int teamId = jdbc.queryForObject(
            "INSERT INTO teams (name) VALUES (?) RETURNING id",
            Integer.class, "t-" + SEQ.getAndIncrement());
        int apiKeyId = jdbc.queryForObject(
            "INSERT INTO api_keys (key_value, name, team_id) VALUES (?, ?, ?) RETURNING id",
            Integer.class, "lg-" + SEQ.getAndIncrement(), "k-" + SEQ.get(), teamId);

        GatewayKey key = new GatewayKey(apiKeyId, "lg-x", "k", ApiKeyType.developer,
            teamId, null, "test", false, null, 0);
        GatewayDeployment deployment = new GatewayDeployment(modelId, "m", providerId, "p",
            "cloud", "openai", "http://x", "/v1/chat/completions",
            "Authorization", "Bearer %s", "sk-x", "BILLING", null);
        return new Fixture(modelId, providerId, key, deployment);
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

    /** What the request is actually billed, through the same view budgets read. */
    private Long cost(int logEntryId) {
        return jdbc.queryForObject(
            "SELECT cost_micro_cents FROM log_entry_cost WHERE log_entry_id = ?", Long.class, logEntryId);
    }

    private Long settledCost(int logEntryId) {
        return jdbc.queryForObject(
            "SELECT settled_cost_micro_cents FROM log_entry WHERE id = ?", Long.class, logEntryId);
    }

    private String status(int logEntryId) {
        return jdbc.queryForObject(
            "SELECT result_status::text FROM log_entry WHERE id = ?", String.class, logEntryId);
    }

    private Map<String, Integer> usageTokens(int logEntryId) {
        Map<String, Integer> out = new java.util.LinkedHashMap<>();
        jdbc.query("SELECT tt.name, ut.token_count FROM usage_tokens ut "
            + "JOIN token_types tt ON tt.id = ut.type_id WHERE ut.log_entry_id = ?",
            rs -> {
                out.put(rs.getString(1), rs.getInt(2));
            }, logEntryId);
        return out;
    }
}
