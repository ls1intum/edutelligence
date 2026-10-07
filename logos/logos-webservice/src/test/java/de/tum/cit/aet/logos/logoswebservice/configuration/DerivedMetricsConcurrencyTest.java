package de.tum.cit.aet.logos.logoswebservice.configuration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.reset;

import java.math.BigDecimal;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Delayed;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import javax.sql.DataSource;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.ConnectionHolder;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.scheduling.Trigger;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ConnectModelProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelProvider;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelPairMetricsProjection;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TokenPriceRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelMetricsService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ProviderService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorNotificationService;

/**
 * Concurrency coverage for three derived-metrics races: price selection that
 * waited behind a provider-type change, a weight-phase snapshot that mixes
 * an old cloud classification with a new local cost, and a delayed pair
 * endpoint/key edit that would flush stale derived columns over a committed
 * derivation or invalidation. Runs against the real Postgres container.
 */
@SpringBootTest
@Import({TestContainersConfig.class, DerivedMetricsConcurrencyTest.SchedulingDisabled.class})
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    "logos.auth.roles.logos-admin=itg-admin",
    "logos.auth.roles.app-admin=chair-member",
    "logos.auth.sync-debounce-minutes=5"
})
@Sql(scripts = {"/sql/cleanup-metrics.sql", "/sql/seed-metrics.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-metrics.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class DerivedMetricsConcurrencyTest {

    @Autowired
    ModelMetricsService modelMetricsService;
    @Autowired
    ProviderService providerService;
    @Autowired
    TokenPriceRepository tokenPriceRepository;
    @Autowired
    JdbcTemplate jdbc;
    @Autowired
    DataSource dataSource;
    @Autowired
    PlatformTransactionManager transactionManager;

    @MockitoSpyBean
    ProviderRepository providerRepository;
    @MockitoSpyBean
    ModelRepository modelRepository;
    @Autowired
    ModelProviderRepository modelProviderRepository;

    @MockitoBean
    JwtDecoder jwtDecoder;
    @MockitoBean
    OrchestratorNotificationService orchestratorNotificationService;
    @MockitoBean
    PriceUpdaterService priceUpdaterService;

    @TestConfiguration
    static class SchedulingDisabled {
        @Bean
        TaskScheduler taskScheduler() {
            ScheduledFuture<?> done = new FinishedFuture();
            return new TaskScheduler() {
                @Override
                public ScheduledFuture<?> schedule(Runnable task, Trigger trigger) { return done; }
                @Override
                public ScheduledFuture<?> schedule(Runnable task, Instant startTime) { return done; }
                @Override
                public ScheduledFuture<?> scheduleAtFixedRate(Runnable task, Instant startTime, Duration fixedRate) { return done; }
                @Override
                public ScheduledFuture<?> scheduleAtFixedRate(Runnable task, Duration fixedRate) { return done; }
                @Override
                public ScheduledFuture<?> scheduleWithFixedDelay(Runnable task, Instant startTime, Duration fixedDelay) { return done; }
                @Override
                public ScheduledFuture<?> scheduleWithFixedDelay(Runnable task, Duration fixedDelay) { return done; }
            };
        }

        record FinishedFuture() implements ScheduledFuture<Object> {
            @Override public long getDelay(TimeUnit unit) { return 0; }
            @Override public int compareTo(Delayed other) { return 0; }
            @Override public boolean cancel(boolean mayInterruptIfRunning) { return true; }
            @Override public boolean isCancelled() { return true; }
            @Override public boolean isDone() { return true; }
            @Override public Object get() { return null; }
            @Override public Object get(long timeout, TimeUnit unit) { return null; }
        }
    }

    /**
     * Derivation's transaction-start {@code NOW()} is fixed when its provider
     * lock wait begins. A cloud-type change that holds that lock can close the
     * old prices and commit before derivation proceeds: with {@code NOW()},
     * those closed rows still look current ({@code valid_to} is after the
     * frozen stamp) and an empty refresh would repopulate the previous
     * catalogue cost. {@code statement_timestamp()} evaluates after the wait.
     */
    @Test
    void derivationWaitingBehindCloudTypeChange_doesNotSelectClosedPrices() throws Exception {
        reset(priceUpdaterService);
        modelMetricsService.deriveAllMetrics();
        assertThat(costOf(5101, 6101)).isEqualByComparingTo(new BigDecimal("0.015"));

        TransactionTemplate typeChangeTx = new TransactionTemplate(transactionManager);
        CountDownLatch typeChangeHoldsLock = new CountDownLatch(1);
        CountDownLatch releaseTypeChange = new CountDownLatch(1);

        try (ExecutorService typeChangePool = Executors.newSingleThreadExecutor();
             ExecutorService derivationPool = Executors.newSingleThreadExecutor()) {
            Future<Integer> typeChange = typeChangePool.submit(() -> typeChangeTx.execute(status -> {
                // Mirrors ProviderService.updateProvider after the type-change
                // branch: lock, close open prices, switch the cloud type,
                // invalidate derived costs. No new catalogue rows (empty
                // refresh).
                providerRepository.lockProviderDerivation(
                    ModelMetricsService.providerDerivationLockKey(6101));
                tokenPriceRepository.closeCurrentPricesByProviderId(6101);
                jdbc.update("UPDATE providers SET cloud_provider_type = 'anthropic' WHERE id = 6101");
                modelProviderRepository.invalidateDerivedCostByProviderId(6101);
                typeChangeHoldsLock.countDown();
                try {
                    if (!releaseTypeChange.await(30, TimeUnit.SECONDS)) {
                        status.setRollbackOnly();
                        return 0;
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    status.setRollbackOnly();
                    return 0;
                }
                return 1;
            }));

            assertThat(typeChangeHoldsLock.await(10, TimeUnit.SECONDS))
                .as("the type change holds the provider lock with prices closed")
                .isTrue();

            Future<Integer> derivation = derivationPool.submit(() -> {
                modelMetricsService.deriveForModel(5101);
                return 1;
            });

            assertThat(awaitLockWaiter())
                .as("derivation waited behind the type change's provider lock")
                .isTrue();

            releaseTypeChange.countDown();
            assertThat(typeChange.get(30, TimeUnit.SECONDS)).isEqualTo(1);
            assertThat(derivation.get(30, TimeUnit.SECONDS)).isEqualTo(1);
        }

        // Empty refresh: no open price for the new type, so derivation must
        // not resurrect the closed openai catalogue blend.
        assertThat(jdbc.queryForObject(
            "SELECT COUNT(*) FROM token_prices WHERE provider_id = 6101 AND valid_to IS NULL",
            Integer.class)).isZero();
        assertThat(costOf(5101, 6101)).isNull();
        assertThat(costOf(5102, 6101)).isNull();
    }

    /**
     * The weight phase used to read provider types and pair costs in separate
     * statements. A cloud-to-local change and its local-cost derivation can
     * commit between those reads under READ COMMITTED: the cloud-id set still
     * includes the provider while findAll returns its new USD/request cost,
     * which would be ranked as USD/M tokens. The population is now built from
     * one joined snapshot; parking before that snapshot while a switch and
     * re-derive commit proves the local cost is never ranked as cloud.
     */
    @Test
    void weightPhaseJoinedSnapshot_ignoresLocalCostAfterCloudToLocalSwitch() throws Exception {
        reset(priceUpdaterService);
        reset(modelRepository);
        jdbc.update("UPDATE providers SET total_vram_mb = 8000 WHERE id = 6101");
        modelMetricsService.deriveAllMetrics();
        assertThat(weightCost(5101)).isEqualTo(4);
        assertThat(weightCost(5102)).isEqualTo(-4);
        assertThat(costOf(5101, 6101)).isEqualByComparingTo(new BigDecimal("0.015"));

        // Park after the weight phase takes its lock and before the joined
        // pair snapshot: a type change + local re-derive that commits in that
        // window is what separate provider/pair reads used to mix.
        CountDownLatch parkedBeforeSnapshot = new CountDownLatch(1);
        CountDownLatch releaseSnapshot = new CountDownLatch(1);
        AtomicBoolean parkOnce = new AtomicBoolean(true);
        doAnswer(inv -> {
            executeOnTransactionConnection("SELECT pg_advisory_xact_lock(?)", (Object) inv.getArgument(0));
            if (parkOnce.compareAndSet(true, false)) {
                parkedBeforeSnapshot.countDown();
                if (!releaseSnapshot.await(30, TimeUnit.SECONDS)) {
                    throw new IllegalStateException("snapshot release timed out");
                }
            }
            return null;
        }).when(modelRepository).lockModelWeights(anyLong());

        try (ExecutorService weightPool = Executors.newSingleThreadExecutor();
             ExecutorService switchPool = Executors.newSingleThreadExecutor()) {
            Future<Integer> weights = weightPool.submit(() -> {
                modelMetricsService.deriveAllMetrics();
                return 1;
            });

            assertThat(parkedBeforeSnapshot.await(10, TimeUnit.SECONDS))
                .as("the weight phase parked after its lock, before the joined snapshot")
                .isTrue();

            Future<Integer> typeSwitch = switchPool.submit(() -> {
                providerService.updateProvider(
                    new UpdateProviderRequestDTO(6101, null, null, null, null, null, null, "none", null));
                awaitUntil(() -> {
                    BigDecimal c = costOf(5101, 6101);
                    return c != null && c.compareTo(new BigDecimal("0.001")) < 0;
                });
                return 1;
            });
            assertThat(typeSwitch.get(60, TimeUnit.SECONDS)).isEqualTo(1);

            releaseSnapshot.countDown();
            assertThat(weights.get(30, TimeUnit.SECONDS)).isEqualTo(1);
        }

        // Local $/request costs are on the pairs for display, but with no
        // cloud pair left the cost weights fall back to the default instead
        // of ranking the local figure as USD/M tokens.
        assertThat(costOf(5101, 6101)).isNotNull();
        assertThat(costOf(5101, 6101)).isLessThan(new BigDecimal("0.001"));
        assertThat(weightCost(5101)).isZero();
        assertThat(weightCost(5102)).isZero();

        List<ModelPairMetricsProjection> snapshot = modelProviderRepository.findPairMetrics(null);
        assertThat(snapshot).isNotEmpty();
        assertThat(snapshot.stream()
            .filter(row -> row.getCloudProviderType() != null)
            .filter(row -> row.getDerivedCostUsd() != null)
            .toList()).isEmpty();
    }

    /**
     * {@code connectModelProvider} loads an existing pair, edits key/endpoint,
     * and saves without the provider advisory lock. Without
     * {@code updatable = false} on the derived columns, Hibernate's full-row
     * flush would restore stale derived metrics overwritten by a concurrent
     * native derivation or type-change invalidation.
     */
    @Test
    void delayedPairEdit_preservesNativeMetricUpdatesAndInvalidation() throws Exception {
        modelMetricsService.deriveAllMetrics();
        assertThat(costOf(5101, 6101)).isEqualByComparingTo(new BigDecimal("0.015"));
        Instant baselineUpdatedAt = updatedAt(5101, 6101);

        TransactionTemplate editTx = new TransactionTemplate(transactionManager);
        CountDownLatch loaded = new CountDownLatch(1);
        CountDownLatch releaseEdit = new CountDownLatch(1);

        try (ExecutorService editPool = Executors.newSingleThreadExecutor();
             ExecutorService nativePool = Executors.newSingleThreadExecutor()) {
            Future<Integer> edit = editPool.submit(() -> editTx.execute(status -> {
                // Same load-edit-save shape as ProviderService.connectModelProvider
                // for an existing pair, without taking the provider lock.
                ModelProvider mp = modelProviderRepository
                    .findByModelIdAndProviderId(5101, 6101).orElseThrow();
                loaded.countDown();
                try {
                    if (!releaseEdit.await(30, TimeUnit.SECONDS)) {
                        status.setRollbackOnly();
                        return 0;
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    status.setRollbackOnly();
                    return 0;
                }
                mp.setApiKey("rotated-key");
                mp.setEndpoint("https://rotated.example/v1");
                modelProviderRepository.save(mp);
                return 1;
            }));

            assertThat(loaded.await(10, TimeUnit.SECONDS))
                .as("the pair edit loaded the stale derived columns")
                .isTrue();

            Future<Integer> nativeWrite = nativePool.submit(() -> {
                // Native invalidation + a fresh latency stamp, as a type-change
                // invalidation and a later derivation would write.
                modelProviderRepository.invalidateDerivedCostByProviderId(6101);
                modelProviderRepository.updateDerivedMetrics(
                    5101, 6101, 111, 555, 22, null, 12, Instant.now());
                return 1;
            });
            assertThat(nativeWrite.get(30, TimeUnit.SECONDS)).isEqualTo(1);
            assertThat(costOf(5101, 6101)).isNull();
            assertThat(jdbc.queryForObject(
                "SELECT derived_ttft_ms FROM model_provider WHERE model_id = 5101 AND provider_id = 6101",
                Integer.class)).isEqualTo(111);

            releaseEdit.countDown();
            assertThat(edit.get(30, TimeUnit.SECONDS)).isEqualTo(1);
        }

        // Endpoint/key edit landed; derived columns kept the native writes.
        assertThat(jdbc.queryForObject(
            "SELECT api_key FROM model_provider WHERE model_id = 5101 AND provider_id = 6101",
            String.class)).isEqualTo("rotated-key");
        assertThat(jdbc.queryForObject(
            "SELECT endpoint FROM model_provider WHERE model_id = 5101 AND provider_id = 6101",
            String.class)).isEqualTo("https://rotated.example/v1");
        assertThat(costOf(5101, 6101)).isNull();
        assertThat(jdbc.queryForObject(
            "SELECT derived_ttft_ms FROM model_provider WHERE model_id = 5101 AND provider_id = 6101",
            Integer.class)).isEqualTo(111);
        assertThat(jdbc.queryForObject(
            "SELECT derived_total_latency_ms FROM model_provider WHERE model_id = 5101 AND provider_id = 6101",
            Integer.class)).isEqualTo(555);
        assertThat(updatedAt(5101, 6101)).isAfter(baselineUpdatedAt);

        // Also through the service entry point used by the admin API.
        providerService.connectModelProvider(
            new ConnectModelProviderRequestDTO(6101, 5101, "https://again.example", "again-key"));
        assertThat(costOf(5101, 6101)).isNull();
        assertThat(jdbc.queryForObject(
            "SELECT derived_ttft_ms FROM model_provider WHERE model_id = 5101 AND provider_id = 6101",
            Integer.class)).isEqualTo(111);
    }

    /**
     * Re-runs SQL on the caller's Spring-managed connection so a spy answer
     * participates in the same transaction and advisory locks as production.
     */
    private void executeOnTransactionConnection(String sql, Object... args) throws Exception {
        ConnectionHolder holder = (ConnectionHolder) TransactionSynchronizationManager.getResource(dataSource);
        Connection connection = holder.getConnection();
        try (PreparedStatement ps = connection.prepareStatement(sql)) {
            for (int i = 0; i < args.length; i++) {
                ps.setObject(i + 1, args[i]);
            }
            ps.execute();
        }
    }

    private boolean awaitLockWaiter() throws InterruptedException {
        long deadline = System.currentTimeMillis() + 15_000;
        while (System.currentTimeMillis() < deadline) {
            Long waiting = jdbc.queryForObject(
                "SELECT COUNT(*) FROM pg_stat_activity "
                    + "WHERE wait_event_type = 'Lock' "
                    + "AND query ILIKE '%pg_advisory_xact_lock%' "
                    + "AND pid <> pg_backend_pid()",
                Long.class);
            if (waiting != null && waiting > 0) {
                return true;
            }
            Thread.sleep(50);
        }
        return false;
    }

    private void awaitUntil(java.util.function.BooleanSupplier condition) throws InterruptedException {
        long deadline = System.currentTimeMillis() + 30_000;
        while (System.currentTimeMillis() < deadline) {
            if (condition.getAsBoolean()) {
                return;
            }
            Thread.sleep(50);
        }
        throw new AssertionError("condition not met within timeout");
    }

    private BigDecimal costOf(int modelId, int providerId) {
        return jdbc.queryForObject(
            "SELECT derived_cost_usd FROM model_provider WHERE model_id = ? AND provider_id = ?",
            BigDecimal.class, modelId, providerId);
    }

    private Integer weightCost(int modelId) {
        return jdbc.queryForObject("SELECT weight_cost FROM models WHERE id = ?", Integer.class, modelId);
    }

    private Instant updatedAt(int modelId, int providerId) {
        return jdbc.queryForObject(
            "SELECT derived_updated_at FROM model_provider WHERE model_id = ? AND provider_id = ?",
            java.sql.Timestamp.class, modelId, providerId).toInstant();
    }
}
