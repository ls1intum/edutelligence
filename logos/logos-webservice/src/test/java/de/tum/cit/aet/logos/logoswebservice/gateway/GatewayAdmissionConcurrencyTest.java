package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import javax.sql.DataSource;

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

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/**
 * What admission on the direct-cloud path may and may not do.
 *
 * <p>Requests on one API key have to run concurrently, on one replica and
 * across replicas, and admitting one must cost the same whether the key has
 * ten rows this month or a million. So admission takes no lock on the key,
 * does not sweep the table for stale reservations, and does not throw away the
 * budget snapshot to re-price the month — it adds its own reservation to the
 * snapshot instead. These cases pin each of those down; the first would hang
 * against an admission that still serialized on the key row.
 */
@SpringBootTest
@Testcontainers
class GatewayAdmissionConcurrencyTest {

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    NamedParameterJdbcTemplate namedJdbc;

    @Autowired
    DataSource dataSource;

    @Autowired
    ObjectMapper objectMapper;

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
        // The stale sweep is asserted on explicitly below; keep the scheduled
        // one from running into the middle of a case.
        registry.add("logos.gateway.budget-reservation-reconcile-seconds", () -> "3600");
    }

    private static final AtomicInteger SEQ = new AtomicInteger(1);
    private static final long RESERVATION = 1_000_000L;

    private static final byte[] REQUEST_BODY =
        "{\"model\":\"m\",\"messages\":[]}".getBytes(StandardCharsets.UTF_8);

    // ------------------------------------------------------------ no key lock

    @Test
    void admission_doesNotWaitForAnotherAdmissionOnTheSameKey() throws Exception {
        Fixture f = seedFixture(ApiKeyType.application);

        // Another admission on this key is mid-transaction: its reservation row
        // is inserted but not yet committed. The insert references the key, so
        // it holds a KEY SHARE lock on the api_keys row for as long as it runs.
        // Admissions must coexist with that — a FOR UPDATE on the key row would
        // queue behind it, and every request on the key behind that.
        CountDownLatch locked = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        CompletableFuture<Void> holder = CompletableFuture.runAsync(() -> {
            try (Connection c = dataSource.getConnection()) {
                c.setAutoCommit(false);
                try (PreparedStatement ps = c.prepareStatement(
                        "INSERT INTO log_entry (timestamp_request, api_key_id, request_id) VALUES (NOW(), ?, ?)")) {
                    ps.setInt(1, f.apiKeyId());
                    ps.setString(2, "gw-holder-" + SEQ.getAndIncrement());
                    ps.executeUpdate();
                }
                locked.countDown();
                release.await(30, TimeUnit.SECONDS);
                c.rollback();
            } catch (Exception e) {
                throw new IllegalStateException(e);
            }
        });
        assertThat(locked.await(10, TimeUnit.SECONDS)).isTrue();

        try {
            Integer logId = CompletableFuture
                .supplyAsync(() -> accounting.admitAndReserve(f.key(), f.deployment(), null, REQUEST_BODY))
                .get(5, TimeUnit.SECONDS);

            assertThat(logId).isNotNull();
            assertThat(settledCost(logId)).isEqualTo(RESERVATION);
        } finally {
            release.countDown();
            holder.get(10, TimeUnit.SECONDS);
        }
    }

    @Test
    void admissionsOnOneKey_runConcurrently() throws Exception {
        Fixture f = seedFixture(ApiKeyType.application);
        int requests = 16;

        // Fire every admission at once; each must land its own reservation.
        CountDownLatch start = new CountDownLatch(1);
        @SuppressWarnings("unchecked")
        CompletableFuture<Integer>[] admissions = new CompletableFuture[requests];
        for (int i = 0; i < requests; i++) {
            admissions[i] = CompletableFuture.supplyAsync(() -> {
                try {
                    start.await(10, TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                return accounting.admitAndReserve(f.key(), f.deployment(), null, REQUEST_BODY);
            });
        }
        start.countDown();
        CompletableFuture.allOf(admissions).get(30, TimeUnit.SECONDS);

        for (CompletableFuture<Integer> admission : admissions) {
            assertThat(admission.get()).isNotNull();
        }
        assertThat(inFlightReservations(f.apiKeyId())).isEqualTo(requests);
    }

    // --------------------------------------------------------- no table sweep

    @Test
    void admission_leavesStaleReservationsToTheScheduledSweep() {
        Fixture f = seedFixture(ApiKeyType.application);
        int stale = admit(f);
        jdbc.update("UPDATE log_entry SET timestamp_request = NOW() - INTERVAL '2 hours' WHERE id = ?", stale);

        // A later request on the same key is admitted without touching the
        // stale row: the sweep is table-wide work and belongs to the schedule.
        admit(f);
        assertThat(status(stale)).isNull();
        assertThat(settledCost(stale)).isEqualTo(RESERVATION);

        accounting.reconcileStale();
        assertThat(status(stale)).isEqualTo("error");
        assertThat(settledCost(stale)).isZero();
    }

    // ------------------------------------------- snapshot sees own reservations

    @Test
    void admissionsOnOneInstance_seeEachOthersReservationsWithoutReloading() {
        // A snapshot that never expires: whatever the second and third
        // admission see, they see because the first one wrote it there.
        GatewayBudgetService snapshot = new GatewayBudgetService(
            namedJdbc, 3600, Clock.fixed(Instant.parse("2026-09-28T09:00:00Z"), ZoneOffset.UTC));
        GatewayCloudAccounting local = new GatewayCloudAccounting(
            namedJdbc, snapshot, objectMapper, RESERVATION, 30);
        Fixture f = seedFixture(ApiKeyType.application);
        setKeyBudget(f.apiKeyId(), 2 * RESERVATION);
        snapshot.enforceCloudBudget(f.key());

        assertThat(local.admitAndReserve(f.key(), f.deployment(), null, REQUEST_BODY)).isNotNull();
        assertThat(local.admitAndReserve(f.key(), f.deployment(), null, REQUEST_BODY)).isNotNull();
        assertThatThrownBy(() -> local.admitAndReserve(f.key(), f.deployment(), null, REQUEST_BODY))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(e -> assertThat(((ResponseStatusException) e).getStatusCode())
                .isEqualTo(HttpStatus.PAYMENT_REQUIRED));

        assertThat(inFlightReservations(f.apiKeyId())).isEqualTo(2);
    }

    @Test
    void developerKeyReservation_countsAgainstTheTeamSnapshotToo() {
        GatewayBudgetService snapshot = new GatewayBudgetService(
            namedJdbc, 3600, Clock.fixed(Instant.parse("2026-09-28T09:00:00Z"), ZoneOffset.UTC));
        GatewayCloudAccounting local = new GatewayCloudAccounting(
            namedJdbc, snapshot, objectMapper, RESERVATION, 30);
        Fixture f = seedFixture(ApiKeyType.developer);
        setTeamBudget(f.teamId(), 2 * RESERVATION);
        snapshot.enforceCloudBudget(f.key());

        assertThat(local.admitAndReserve(f.key(), f.deployment(), null, REQUEST_BODY)).isNotNull();
        assertThat(local.admitAndReserve(f.key(), f.deployment(), null, REQUEST_BODY)).isNotNull();
        assertThatThrownBy(() -> local.admitAndReserve(f.key(), f.deployment(), null, REQUEST_BODY))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("Team monthly budget exceeded");
    }

    // --------------------------------------------------- shared RPM / TPM

    @Test
    void admission_storesTheTokenEstimateOnTheReservation() {
        Fixture f = seedFixture(ApiKeyType.application);
        int estimate = GatewayCloudRateLimiter.estimateTokens(REQUEST_BODY);
        Integer logId = accounting.admitAndReserve(
            f.key(), f.deployment(), null, null, estimate, REQUEST_BODY);

        assertThat(logId).isNotNull();
        assertThat(jdbc.queryForObject(
            "SELECT gateway_estimated_tokens FROM log_entry WHERE id = ?", Integer.class, logId))
            .isEqualTo(estimate);
    }

    @Test
    void sharedTpm_rejectsWhenRecentEstimatesWouldExceedTheLimit() {
        // Two admissions land their estimates in the shared window (as if on
        // two replicas). A third that would push the sum past the limit is
        // refused — the same check every replica runs against the same rows.
        Fixture f = seedFixture(ApiKeyType.application);
        int estimate = 400;
        int tpmLimit = 1000;

        assertThat(accounting.admitAndReserve(
            f.key(), f.deployment(), null, tpmLimit, estimate, REQUEST_BODY)).isNotNull();
        assertThat(accounting.admitAndReserve(
            f.key(), f.deployment(), null, tpmLimit, estimate, REQUEST_BODY)).isNotNull();
        assertThatThrownBy(() -> accounting.admitAndReserve(
                f.key(), f.deployment(), null, tpmLimit, estimate, REQUEST_BODY))
            .isInstanceOf(ResponseStatusException.class)
            .satisfies(e -> assertThat(((ResponseStatusException) e).getStatusCode())
                .isEqualTo(HttpStatus.TOO_MANY_REQUESTS))
            .hasMessageContaining("TPM limit reached");

        assertThat(inFlightReservations(f.apiKeyId())).isEqualTo(2);
        assertThat(recentEstimatedTokens(f.apiKeyId())).isEqualTo(800);
    }

    @Test
    void sharedRpm_rejectsWhenRecentGatewayRowsReachTheLimit() {
        Fixture f = seedFixture(ApiKeyType.application);
        int rpmLimit = 2;

        assertThat(accounting.admitAndReserve(
            f.key(), f.deployment(), rpmLimit, null, 10, REQUEST_BODY)).isNotNull();
        assertThat(accounting.admitAndReserve(
            f.key(), f.deployment(), rpmLimit, null, 10, REQUEST_BODY)).isNotNull();
        assertThatThrownBy(() -> accounting.admitAndReserve(
                f.key(), f.deployment(), rpmLimit, null, 10, REQUEST_BODY))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("RPM limit reached");

        assertThat(inFlightReservations(f.apiKeyId())).isEqualTo(2);
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

    private void setKeyBudget(int apiKeyId, long microCents) {
        jdbc.update("UPDATE api_keys SET settings = jsonb_build_object('budget_limit_micro_cents', ?::bigint) "
            + "WHERE id = ?", microCents, apiKeyId);
    }

    private void setTeamBudget(int teamId, long microCents) {
        jdbc.update("UPDATE teams SET team_monthly_budget_micro_cents = ? WHERE id = ?", microCents, teamId);
    }

    private Fixture seedFixture(ApiKeyType keyType) {
        int modelId = jdbc.queryForObject(
            "INSERT INTO models (name) VALUES (?) RETURNING id",
            Integer.class, "m-" + SEQ.getAndIncrement());
        int providerId = jdbc.queryForObject(
            "INSERT INTO providers (name, base_url, provider_type, cloud_provider_type, auth_name, auth_format) "
            + "VALUES (?, 'http://x', 'cloud', 'openai'::cloud_provider_type_enum, 'Authorization', 'Bearer %s') "
            + "RETURNING id",
            Integer.class, "p-" + SEQ.getAndIncrement());
        // High defaults keep the limits a case does not set out of the way.
        int teamId = jdbc.queryForObject(
            "INSERT INTO teams (name, default_monthly_budget_micro_cents, team_monthly_budget_micro_cents) "
            + "VALUES (?, 1000000000, 1000000000) RETURNING id",
            Integer.class, "t-" + SEQ.getAndIncrement());
        int apiKeyId = jdbc.queryForObject(
            "INSERT INTO api_keys (key_value, name, team_id, key_type, log) "
            + "VALUES (?, ?, ?, ?::api_key_type_enum, 'BILLING'::logging_enum) RETURNING id",
            Integer.class, "lg-" + SEQ.getAndIncrement(), "k-" + SEQ.get(), teamId, keyType.name());

        GatewayKey key = new GatewayKey(apiKeyId, "lg-x", "k", keyType,
            teamId, null, "test", false, null, 0, "BILLING");
        GatewayDeployment deployment = new GatewayDeployment(modelId, "m", providerId, "p",
            "cloud", "openai", "http://x", "/v1/chat/completions",
            "Authorization", "Bearer %s", "sk-x", "BILLING", null);
        return new Fixture(modelId, providerId, teamId, apiKeyId, key, deployment);
    }

    private Long settledCost(int logEntryId) {
        return jdbc.queryForObject(
            "SELECT settled_cost_micro_cents FROM log_entry WHERE id = ?", Long.class, logEntryId);
    }

    private String status(int logEntryId) {
        return jdbc.queryForObject(
            "SELECT result_status::text FROM log_entry WHERE id = ?", String.class, logEntryId);
    }

    private int inFlightReservations(int apiKeyId) {
        Integer n = jdbc.queryForObject(
            "SELECT COUNT(*)::int FROM log_entry WHERE api_key_id = ? AND result_status IS NULL "
            + "AND request_id LIKE 'gw-%'", Integer.class, apiKeyId);
        return n == null ? 0 : n;
    }

    private long recentEstimatedTokens(int apiKeyId) {
        Long n = jdbc.queryForObject(
            "SELECT COALESCE(SUM(gateway_estimated_tokens), 0)::bigint FROM log_entry "
            + "WHERE api_key_id = ? AND request_id LIKE 'gw-%' "
            + "AND timestamp_request > NOW() - INTERVAL '60 seconds'",
            Long.class, apiKeyId);
        return n == null ? 0L : n;
    }
}
