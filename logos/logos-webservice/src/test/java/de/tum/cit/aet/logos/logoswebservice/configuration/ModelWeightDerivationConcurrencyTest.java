package de.tum.cit.aet.logos.logoswebservice.configuration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.fail;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Delayed;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.scheduling.Trigger;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelMetricsService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelWeightService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorNotificationService;

/**
 * Concurrency coverage for the model-weights lock that serializes the
 * auto-derivation's weight phase with the unversioned full-row model saves
 * of the admin endpoints and the weight rebalances they (or a future direct
 * caller) trigger. Model has no @Version, so a save that loaded a model
 * before a derivation committed flushes the stale weight columns and
 * override map back on its Hibernate update unless the writer took the lock
 * before loading. These tests run against the real Postgres container, so
 * the advisory-lock behaviour is exercised end to end.
 */
@SpringBootTest
@Import({TestContainersConfig.class, ModelWeightDerivationConcurrencyTest.SchedulingDisabled.class})
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
class ModelWeightDerivationConcurrencyTest {

    @Autowired
    ModelService modelService;
    @Autowired
    ModelMetricsService modelMetricsService;
    @Autowired
    ModelWeightService modelWeightService;
    @Autowired
    ModelRepository modelRepository;
    @Autowired
    JdbcTemplate jdbc;
    @Autowired
    PlatformTransactionManager transactionManager;

    @MockitoBean
    JwtDecoder jwtDecoder;
    // The weight run notifies the orchestrator after commit; keep that off
    // the real websocket in this context.
    @MockitoBean
    OrchestratorNotificationService orchestratorNotificationService;
    // The catalogue refresh would reach the live litellm catalog; nothing
    // here needs it, so mock it like the other metrics tests do.
    @MockitoBean
    PriceUpdaterService priceUpdaterService;

    /**
     * The startup @Scheduled runs (metrics derivation, price and capability
     * refreshes) would move the weights out from under the interleavings
     * below. A no-op TaskScheduler makes this context deterministic - the
     * tests call the derivation methods directly.
     */
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

        /** A finished future returned by the no-op scheduler. */
        record FinishedFuture() implements ScheduledFuture<Object> {
            @Override
            public long getDelay(TimeUnit unit) { return 0; }
            @Override
            public int compareTo(Delayed other) { return 0; }
            @Override
            public boolean cancel(boolean mayInterruptIfRunning) { return true; }
            @Override
            public boolean isCancelled() { return true; }
            @Override
            public boolean isDone() { return true; }
            @Override
            public Object get() { return null; }
            @Override
            public Object get(long timeout, TimeUnit unit) { return null; }
        }
    }

    @Test
    void lateAdminSaveDoesNotClobberDerivedWeightsAndPins() throws Exception {
        // Pin the cost dimension first, so the override map is non-trivially
        // asserted at the end: the late full-row flush must not empty it.
        // 5101 is cheapest of the cloud pairs, so the pin visibly deviates
        // from the derived value.
        modelService.updateModelInfo(
            new UpdateModelRequestDTO(5101, null, null, null, null, null, 3, null));

        // A description-only admin save that loaded the model before the
        // derivation committed must not flush the stale weight columns back:
        // its transaction takes the model-weights lock before loading, as the
        // admin endpoints do, so the derivation's weight phase waits for it
        // and writes after the save commits.
        TransactionTemplate adminTx = new TransactionTemplate(transactionManager);
        CountDownLatch loaded = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);

        try (ExecutorService adminPool = Executors.newSingleThreadExecutor();
             ExecutorService derivationPool = Executors.newSingleThreadExecutor()) {
            Future<Integer> admin = adminPool.submit(() -> adminTx.execute(status -> {
                modelRepository.lockModelWeights(ModelMetricsService.MODEL_WEIGHTS_LOCK_KEY);
                Model model = modelRepository.findById(5101).orElseThrow();
                loaded.countDown();
                try {
                    if (!release.await(30, TimeUnit.SECONDS)) {
                        status.setRollbackOnly();
                        return 0;
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    status.setRollbackOnly();
                    return 0;
                }
                model.setDescription("description-only edit");
                modelRepository.save(model);
                return 1;
            }));

            assertThat(loaded.await(10, TimeUnit.SECONDS))
                .as("the admin transaction loaded the model")
                .isTrue();

            Future<Integer> derivation = derivationPool.submit(() -> {
                modelMetricsService.deriveForModel(5101);
                return 1;
            });

            // The derivation's weight phase must be parked on the lock the
            // admin transaction holds: only then does the interleaving below
            // prove the serialization rather than a lucky re-order.
            assertThat(awaitLockWaiter())
                .as("the derivation waited for the admin save's model-weights lock")
                .isTrue();

            release.countDown();
            assertThat(derivation.get(30, TimeUnit.SECONDS)).isEqualTo(1);
            assertThat(admin.get(30, TimeUnit.SECONDS)).isEqualTo(1);
        }

        // Between the admin load and its flush the derivation committed a
        // fresh ranking: the derived weight, the pre-existing pin, and the
        // admin's own description edit must all be visible afterwards.
        assertThat(weightOf(5101, "latency")).isEqualTo(4);
        assertThat(weightOf(5101, "cost")).isEqualTo(3);
        assertThat(overridesOf(5101)).contains("cost");
        assertThat(jdbc.queryForObject("SELECT description FROM models WHERE id = 5101", String.class))
            .isEqualTo("description-only edit");
    }

    @Test
    void updateModelInfoWaitsForInFlightDerivationWeightPhase() throws Exception {
        // While another transaction holds the model-weights lock (as an
        // in-flight derivation's weight phase does), a pinning admin save
        // must wait for it instead of loading the model now and flushing the
        // stale row - weight columns and override map included - later.
        TransactionTemplate holderTx = new TransactionTemplate(transactionManager);
        CountDownLatch held = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);

        try (ExecutorService holderPool = Executors.newSingleThreadExecutor();
             ExecutorService servicePool = Executors.newSingleThreadExecutor()) {
            Future<Integer> holder = holderPool.submit(() -> holderTx.execute(status -> {
                modelRepository.lockModelWeights(ModelMetricsService.MODEL_WEIGHTS_LOCK_KEY);
                held.countDown();
                try {
                    if (!release.await(30, TimeUnit.SECONDS)) {
                        status.setRollbackOnly();
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    status.setRollbackOnly();
                }
                return 1;
            }));
            assertThat(held.await(10, TimeUnit.SECONDS))
                .as("the rival transaction holds the model-weights lock")
                .isTrue();

            Future<Map<String, Object>> service = servicePool.submit(
                () -> modelService.updateModelInfo(
                    new UpdateModelRequestDTO(5101, null, null, null, null, null, 3, null)));

            // The save must be parked on the lock: if it completed while the
            // lock was held, it loaded the model unserialized, and its
            // full-row flush can revert a concurrent derivation.
            boolean parked = false;
            long deadline = System.currentTimeMillis() + 15_000;
            while (System.currentTimeMillis() < deadline) {
                if (service.isDone()) {
                    fail("the admin save completed while the model-weights lock was held");
                }
                if (lockWaiterVisible()) {
                    parked = true;
                    break;
                }
                Thread.sleep(50);
            }
            assertThat(parked)
                .as("the admin save waited on the model-weights lock")
                .isTrue();

            release.countDown();
            service.get(30, TimeUnit.SECONDS);
            holder.get(30, TimeUnit.SECONDS);
        }

        assertThat(weightOf(5101, "cost")).isEqualTo(3);
        assertThat(overridesOf(5101)).contains("cost");
    }

    @Test
    void rebalanceAfterFeedbackWaitsForInFlightDerivationWeightPhase() throws Exception {
        // The rebalances flush every model row they load, so the guarantee
        // must live on the rebalance methods themselves, not only on their
        // current ModelService callers: a direct call has to park on a held
        // model-weights lock instead of loading now and flushing the stale
        // rows later.
        TransactionTemplate holderTx = new TransactionTemplate(transactionManager);
        CountDownLatch held = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);

        try (ExecutorService holderPool = Executors.newSingleThreadExecutor();
             ExecutorService servicePool = Executors.newSingleThreadExecutor()) {
            Future<Integer> holder = holderPool.submit(() -> holderTx.execute(status -> {
                modelRepository.lockModelWeights(ModelMetricsService.MODEL_WEIGHTS_LOCK_KEY);
                held.countDown();
                try {
                    if (!release.await(30, TimeUnit.SECONDS)) {
                        status.setRollbackOnly();
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    status.setRollbackOnly();
                }
                return 1;
            }));
            assertThat(held.await(10, TimeUnit.SECONDS))
                .as("the rival transaction holds the model-weights lock")
                .isTrue();

            Future<Integer> rebalance = servicePool.submit(
                () -> {
                    modelWeightService.rebalanceAfterFeedback(5101, "latency", 1);
                    return 1;
                });

            // The rebalance must be parked on the lock: if it completed while
            // the lock was held, it loaded the model rows unserialized, and
            // its full-row flush can revert a concurrent derivation.
            boolean parked = false;
            long deadline = System.currentTimeMillis() + 15_000;
            while (System.currentTimeMillis() < deadline) {
                if (rebalance.isDone()) {
                    fail("the rebalance completed while the model-weights lock was held");
                }
                if (lockWaiterVisible()) {
                    parked = true;
                    break;
                }
                Thread.sleep(50);
            }
            assertThat(parked)
                .as("the rebalance waited on the model-weights lock")
                .isTrue();

            release.countDown();
            rebalance.get(30, TimeUnit.SECONDS);
            holder.get(30, TimeUnit.SECONDS);
        }

        // The feedback landed only after the wait: 5101 now ranks above 5102
        // on latency, and the rebalance's full-row flush carried that through.
        assertThat(weightOf(5101, "latency")).isGreaterThan(weightOf(5102, "latency"));
    }

    /**
     * Waits up to 15 s for a session blocked on an advisory-lock call: a
     * parked transaction's current query is the lock statement itself.
     */
    private boolean awaitLockWaiter() throws InterruptedException {
        long deadline = System.currentTimeMillis() + 15_000;
        while (System.currentTimeMillis() < deadline) {
            if (lockWaiterVisible()) {
                return true;
            }
            Thread.sleep(50);
        }
        return false;
    }

    private boolean lockWaiterVisible() {
        Long waiting = jdbc.queryForObject(
            "SELECT COUNT(*) FROM pg_stat_activity "
                + "WHERE wait_event_type = 'Lock' "
                + "AND query ILIKE '%pg_advisory_xact_lock%' "
                + "AND pid <> pg_backend_pid()",
            Long.class);
        return waiting != null && waiting > 0;
    }

    private int weightOf(int modelId, String dimension) {
        return jdbc.queryForObject(
            "SELECT weight_" + dimension + " FROM models WHERE id = ?", Integer.class, modelId);
    }

    private String overridesOf(int modelId) {
        return jdbc.queryForObject(
            "SELECT weight_overrides::text FROM models WHERE id = ?", String.class, modelId);
    }
}
