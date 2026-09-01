package de.tum.cit.aet.logos.logoswebservice.configuration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Delayed;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BooleanSupplier;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.dao.InvalidDataAccessResourceUsageException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.scheduling.Trigger;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelMetricsService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ProviderService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorNotificationService;

@SpringBootTest
@AutoConfigureMockMvc
@Import({TestContainersConfig.class, ModelMetricsControllerTest.SchedulingDisabled.class})
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
class ModelMetricsControllerTest {

    @Autowired
    MockMvc mvc;
    @Autowired
    ModelMetricsService modelMetricsService;
    @Autowired
    ProviderService providerService;
    @Autowired
    JdbcTemplate jdbc;
    // Spied (not replaced) so one test can make a single guarded weight
    // update fail and prove the whole weight phase rolls back.
    @MockitoSpyBean
    ModelRepository modelRepository;
    @MockitoBean
    JwtDecoder jwtDecoder;
    // Mocked so the price refresh the derivation waits for never reaches the
    // live litellm catalog; tests install prices via the mock's answer.
    @MockitoBean
    PriceUpdaterService priceUpdaterService;
    @MockitoBean
    OrchestratorNotificationService orchestratorNotificationService;

    /**
     * The @Scheduled derivation run (initialDelay = 0) fires on the scheduler
     * thread at context startup and can land between a test's seed and its
     * assertions: on a slow runner it moves the weights from their seed
     * values and pokes the notification mock, flaking the steady-state test.
     * A no-op TaskScheduler makes this context deterministic - the tests call
     * the derivation methods directly. The websocket handlers create their own
     * executors, so nothing else in the context depends on real scheduling.
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
    void getModelMetrics_returnsPairDerivedMetrics() throws Exception {
        modelMetricsService.deriveAllMetrics();
        mvc.perform(post("/logosdb/get_model_metrics")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5101}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(2))
           .andExpect(jsonPath("$[0].provider_name").value("cloud-provider"))
           .andExpect(jsonPath("$[0].derived_ttft_ms").value(100))
           .andExpect(jsonPath("$[0].derived_total_latency_ms").value(500))
           .andExpect(jsonPath("$[0].derived_tpot_ms").value(44))
           .andExpect(jsonPath("$[0].derived_cost_usd").value(0.015d))
           // 12 warm requests plus row 90053 (success with response but no first token):
           // it feeds the total-latency p50, so it counts as a sample
           .andExpect(jsonPath("$[0].derived_samples").value(13))
           .andExpect(jsonPath("$[0].derived_updated_at").exists())
           .andExpect(jsonPath("$[1].provider_name").value("local-provider"))
           .andExpect(jsonPath("$[1].derived_ttft_ms").value(9000))
           .andExpect(jsonPath("$[1].derived_total_latency_ms").value(40000))
           .andExpect(jsonPath("$[1].derived_tpot_ms").value(3444))
           .andExpect(jsonPath("$[1].derived_cost_usd").value(0.008889d))
           .andExpect(jsonPath("$[1].derived_samples").value(12));
    }

    @Test
    void getModelMetrics_noModelId_returnsAllPairs() throws Exception {
        modelMetricsService.deriveAllMetrics();
        mvc.perform(post("/logosdb/get_model_metrics")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(4));
    }

    @Test
    void deriveAfterPriceRefresh_derivesCostOnlyAfterPriceUpdate() throws Exception {
        // A freshly connected cloud pair has no catalogue price yet, so a
        // derivation that ran before the price update would store a null cost.
        jdbc.update("DELETE FROM token_prices WHERE model_id = 5101 AND provider_id = 6101");
        AtomicInteger priceUpdateRan = new AtomicInteger();
        doAnswer(invocation -> {
            jdbc.update("INSERT INTO token_prices (id, type_id, model_id, provider_id, valid_from, price_per_k_token) "
                + "VALUES (92201, 9101, 5101, 6101, NOW() - INTERVAL '1 year', 1000), "
                + "       (92202, 9102, 5101, 6101, NOW() - INTERVAL '1 year', 2000)");
            priceUpdateRan.set(1);
            return null;
        }).when(priceUpdaterService).updatePricesForModel(eq(5101), anyString());

        // Synchronous entry point: the catalogue refresh runs first, the
        // derivation reads the prices it installed.
        modelMetricsService.deriveAfterPriceRefresh(5101);

        assertThat(priceUpdateRan.get()).isEqualTo(1);
        BigDecimal cost = jdbc.queryForObject(
            "SELECT derived_cost_usd FROM model_provider WHERE model_id = 5101 AND provider_id = 6101",
            BigDecimal.class);
        assertThat(cost).isNotNull();
        assertThat(cost.doubleValue()).isEqualTo(0.015);
    }

    @Test
    void deriveAllMetrics_appliesModelWeights() throws Exception {
        modelMetricsService.deriveAllMetrics();
        mvc.perform(post("/logosdb/get_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           // Latency is the best pair per model (5101: cloud 500ms, 5102: local 900ms).
           // Cost is ranked over cloud pairs only (the local $/request figure is
           // display-only, not commensurable): 5101 cloud 0.015 < 5102 cloud 0.06.
           // Weights follow the ModelWeightService scale.
           .andExpect(jsonPath("$[0].weight_latency").value(4))   // 5101 fast
           .andExpect(jsonPath("$[0].weight_cost").value(4))      // 5101 cheaper (cloud)
           .andExpect(jsonPath("$[1].weight_latency").value(-4))  // 5102 slow
           .andExpect(jsonPath("$[1].weight_cost").value(-4))     // 5102 pricier (cloud)
           // accuracy and quality are not derived in v1 - stay at seed values
           .andExpect(jsonPath("$[0].weight_accuracy").value(0))
           .andExpect(jsonPath("$[0].weight_quality").value(0));
    }

    @Test
    void manualWeightOverride_persistsAcrossDerivation() throws Exception {
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5102,\"weight_latency\":42}"))
           .andExpect(status().isOk());
        modelMetricsService.deriveAllMetrics();
        mvc.perform(post("/logosdb/get_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[1].weight_latency").value(42))
           .andExpect(jsonPath("$[0].weight_latency").value(4));
        String overrides = jdbc.queryForObject("SELECT weight_overrides::text FROM models WHERE id=5102", String.class);
        assertThat(overrides).contains("latency");
    }

    @Test
    void unchangedWeight_doesNotMarkOverride() throws Exception {
        modelMetricsService.deriveAllMetrics();
        Integer current = jdbc.queryForObject("SELECT weight_latency FROM models WHERE id=5102", Integer.class);
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5102,\"weight_latency\":" + current + "}"))
           .andExpect(status().isOk());
        String overrides = jdbc.queryForObject("SELECT COALESCE(weight_overrides::text,'{}') FROM models WHERE id=5102", String.class);
        assertThat(overrides).doesNotContain("latency");
    }

    @Test
    void guardedWeightUpdate_leavesPinnedDimensionsAlone() {
        modelMetricsService.deriveAllMetrics();
        // Without a pin the targeted write lands...
        assertThat(modelRepository.updateWeightLatencyGuarded(5101, 7)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT weight_latency FROM models WHERE id = 5101", Integer.class)).isEqualTo(7);
        // ...a pin committed in the meantime (e.g. by a concurrent admin edit)
        // makes the very same UPDATE a no-op, because the guard is re-checked
        // in the WHERE clause at write time.
        jdbc.update("UPDATE models SET weight_overrides = '{\"latency\": true}' WHERE id = 5101");
        assertThat(modelRepository.updateWeightLatencyGuarded(5101, 9)).isEqualTo(0);
        assertThat(jdbc.queryForObject("SELECT weight_latency FROM models WHERE id = 5101", Integer.class)).isEqualTo(7);
    }

    @Test
    void weightPhaseFailure_rollsBackAllWeightWritesAndSkipsNotification() {
        // First run commits the derived weights. Reset the stored values so
        // the failing run below has real writes that a rollback must undo.
        modelMetricsService.deriveAllMetrics();
        jdbc.update("UPDATE models SET weight_latency = 0, weight_cost = 0 WHERE id IN (5101, 5102)");
        clearInvocations(orchestratorNotificationService);
        // A failure on one row of the weight loop must roll back the whole
        // compare-and-update phase, including the earlier successful writes.
        doThrow(new InvalidDataAccessResourceUsageException("simulated mid-loop failure"))
            .when(modelRepository).updateWeightCostGuarded(eq(5102), anyInt());

        modelMetricsService.deriveAllMetrics();

        // Nothing of the failed run survived: no half re-ranked fleet...
        for (int id : new int[] {5101, 5102}) {
            assertThat(jdbc.queryForObject("SELECT weight_latency FROM models WHERE id = ?", Integer.class, id)).isZero();
            assertThat(jdbc.queryForObject("SELECT weight_cost FROM models WHERE id = ?", Integer.class, id)).isZero();
        }
        // ...and no orchestrator notification for a run that rolled back.
        verifyNoInteractions(orchestratorNotificationService);
    }

    @Test
    void steadyStateDerivation_isNoOpWithoutNotification() {
        // First run moves the weights from their seed values onto the derived
        // scale (and notifies). Clear the bookkeeping so the assertion below
        // only covers the steady-state second run. The startup @Scheduled run
        // is disabled in this context (SchedulingDisabled), so only these two
        // calls can poke the mock.
        modelMetricsService.deriveAllMetrics();
        clearInvocations(orchestratorNotificationService);
        // Second run: every derived weight already equals the stored one, so
        // nothing is written and the orchestrator is not poked.
        modelMetricsService.deriveAllMetrics();
        verifyNoInteractions(orchestratorNotificationService);
    }

    @Test
    void explicitWeightOverrides_replacesOverrideSet() throws Exception {
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5102,\"weight_latency\":42}"))
           .andExpect(status().isOk());
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5102,\"weight_overrides\":{}}"))
           .andExpect(status().isOk());
        String overrides = jdbc.queryForObject("SELECT weight_overrides::text FROM models WHERE id=5102", String.class);
        assertThat(overrides).isEqualTo("{}");
        modelMetricsService.deriveAllMetrics();
        mvc.perform(post("/logosdb/get_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[1].weight_latency").value(-4));
    }

    @Test
    void feedbackEndpoint_marksCategoryOverride() throws Exception {
        modelMetricsService.deriveAllMetrics();
        mvc.perform(post("/logosdb/update_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5101,\"category\":\"quality\",\"value\":2}"))
           .andExpect(status().isOk());
        String overrides = jdbc.queryForObject("SELECT weight_overrides::text FROM models WHERE id=5101", String.class);
        assertThat(overrides).contains("quality");
    }

    @Test
    void appAdmin_getModelMetrics_forbidden() throws Exception {
        modelMetricsService.deriveAllMetrics();
        mvc.perform(post("/logosdb/get_model_metrics")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"model_id\":5101}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void providerTypeChangeLocalToCloud_invalidatesCostAndRederivesInNewUnit() throws Exception {
        // Baseline: under the current type the local pairs hold the
        // VRAM x latency proxy, in USD per request.
        modelMetricsService.deriveAllMetrics();
        assertThat(costOf(5101, 6102)).isEqualByComparingTo(new BigDecimal("0.008889"));

        // Park both async re-derivations at the price update - their first
        // step, before any pair is re-derived - so the invalidated state is
        // observable in between. The first parked task installs the
        // catalogue prices and only then lets the second proceed, so both
        // re-derivations read the same prices.
        CountDownLatch parked = new CountDownLatch(2);
        CountDownLatch release = new CountDownLatch(1);
        CountDownLatch pricesInstalled = new CountDownLatch(1);
        AtomicInteger priceInstalls = new AtomicInteger();
        doAnswer(inv -> {
            parked.countDown();
            release.await(10, TimeUnit.SECONDS);
            if (priceInstalls.compareAndSet(0, 1)) {
                jdbc.update("INSERT INTO token_prices (id, type_id, model_id, provider_id, valid_from, price_per_k_token) "
                    + "VALUES (92210, 9101, 5101, 6102, NOW() - INTERVAL '1 year', 1000), "
                    + "       (92211, 9102, 5101, 6102, NOW() - INTERVAL '1 year', 2000), "
                    + "       (92212, 9101, 5102, 6102, NOW() - INTERVAL '1 year', 4000), "
                    + "       (92213, 9102, 5102, 6102, NOW() - INTERVAL '1 year', 8000)");
                pricesInstalled.countDown();
            }
            pricesInstalled.await(10, TimeUnit.SECONDS);
            return null;
        }).when(priceUpdaterService).updatePricesForModel(anyInt(), anyString());

        providerService.updateProvider(
            new UpdateProviderRequestDTO(6102, null, null, null, null, null, null, "openai", null));

        // The committed update invalidated the old-unit cost of every
        // affected pair - and only those: the untouched provider 6101 keeps
        // its cloud cost. A ranking running in this window reads NULL, so a
        // USD-per-request figure can never be read as USD per million tokens.
        assertThat(costOf(5101, 6102)).isNull();
        assertThat(costOf(5102, 6102)).isNull();
        assertThat(costOf(5101, 6101)).isEqualByComparingTo(new BigDecimal("0.015"));

        // Release the parked re-derivations: catalogue refresh first, then
        // the re-derivation, then the re-rank.
        assertThat(parked.await(10, TimeUnit.SECONDS)).isTrue();
        release.countDown();
        awaitUntil(() -> costOf(5101, 6102) != null && costOf(5102, 6102) != null);
        // The new-unit values are the catalogue blend (1000/2000 and
        // 4000/8000 per 1K tokens), not the old local proxy.
        assertThat(costOf(5101, 6102)).isEqualByComparingTo(new BigDecimal("0.015"));
        assertThat(costOf(5102, 6102)).isEqualByComparingTo(new BigDecimal("0.06"));
    }

    @Test
    void providerTypeChangeCloudToLocal_invalidatesCostAndRederivesInNewUnit() throws Exception {
        modelMetricsService.deriveAllMetrics();
        assertThat(costOf(5101, 6101)).isEqualByComparingTo(new BigDecimal("0.015"));

        // Give the provider local hardware, so the new-unit (VRAM x latency)
        // cost is derivable after the switch.
        jdbc.update("UPDATE providers SET total_vram_mb = 8000 WHERE id = 6101");

        CountDownLatch parked = new CountDownLatch(2);
        CountDownLatch release = new CountDownLatch(1);
        doAnswer(inv -> {
            parked.countDown();
            release.await(10, TimeUnit.SECONDS);
            return null;
        }).when(priceUpdaterService).updatePricesForModel(anyInt(), anyString());

        providerService.updateProvider(
            new UpdateProviderRequestDTO(6101, null, null, null, null, null, null, "none", null));

        // The cloud-unit costs are gone before the re-derivation runs; the
        // pairs of the untouched provider keep their values.
        assertThat(costOf(5101, 6101)).isNull();
        assertThat(costOf(5102, 6101)).isNull();
        assertThat(costOf(5101, 6102)).isEqualByComparingTo(new BigDecimal("0.008889"));

        assertThat(parked.await(10, TimeUnit.SECONDS)).isTrue();
        release.countDown();
        awaitUntil(() -> costOf(5101, 6101) != null && costOf(5102, 6101) != null);
        // The new-unit values are the VRAM x latency proxy (USD per request):
        // 8000 MB at 0.0001 USD/MB-hour over 500 ms and 3000 ms.
        assertThat(costOf(5101, 6101)).isEqualByComparingTo(new BigDecimal("0.000111"));
        assertThat(costOf(5102, 6101)).isEqualByComparingTo(new BigDecimal("0.000667"));
        // Both models lost their last cloud pair: the stale cloud-derived
        // cost weights fall back to the default instead of surviving on a
        // pair that no longer exists (the local figures are display-only and
        // never feed the cost ranking).
        awaitUntil(() -> weightCost(5101) == 0 && weightCost(5102) == 0);
        assertThat(weightCost(5101)).isZero();
        assertThat(weightCost(5102)).isZero();
    }

    @Test
    void providerDeletion_rederivesAndReranksAffectedModelsImmediately() throws Exception {
        modelMetricsService.deriveAllMetrics();
        // Baseline: 5101 is fastest via its 500 ms cloud pair, 5102 slowest.
        assertThat(weightLatency(5101)).isEqualTo(4);
        assertThat(weightLatency(5102)).isEqualTo(-4);

        providerService.deleteProvider(6101);

        // The pair rows are gone with the provider...
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM model_provider WHERE provider_id = 6101", Integer.class))
            .isZero();
        // ...and the survivors are re-derived and the models re-ranked right
        // away - not at the next daily job. On the local pairs 5102 (900 ms)
        // now beats 5101 (40000 ms), so the latency ranking flips; and both
        // models lost their last cloud pair, so the stale cloud-derived cost
        // weights fall back to the default.
        awaitUntil(() -> weightLatency(5101) == -4 && weightLatency(5102) == 4
            && weightCost(5101) == 0 && weightCost(5102) == 0);
        assertThat(weightLatency(5101)).isEqualTo(-4);
        assertThat(weightLatency(5102)).isEqualTo(4);
        assertThat(weightCost(5101)).isZero();
        assertThat(weightCost(5102)).isZero();
    }

    @Test
    void lastCloudPairDisconnect_clearsStaleCostWeightAndKeepsPins() throws Exception {
        modelMetricsService.deriveAllMetrics();
        // Baseline: both models are ranked on their cloud costs (5101 cheaper).
        assertThat(weightCost(5101)).isEqualTo(4);
        assertThat(weightCost(5102)).isEqualTo(-4);

        // A manually pinned cost weight must survive the population leave.
        jdbc.update("UPDATE models SET weight_cost = 7, weight_overrides = '{\"cost\": true}' WHERE id = 5101");

        // Through the endpoint, so the post-service async re-derivation fires.
        mvc.perform(post("/logosdb/disconnect_model_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5101,\"provider_id\":6101}"))
           .andExpect(status().isOk());

        // 5101 lost its last cloud pair (5102 keeps its 6101 pair): 5101's
        // auto-derived cost weight would fall back to the default, but its
        // pin protects it; 5102, re-ranked alone on the relative scale,
        // lands on the neutral 0. On the surviving local pairs the latency
        // ranking flips (900 ms beats 40000 ms).
        awaitUntil(() -> weightCost(5102) == 0 && weightLatency(5101) == -4 && weightLatency(5102) == 4);
        assertThat(weightCost(5101)).isEqualTo(7);
        assertThat(weightCost(5102)).isZero();
        assertThat(weightLatency(5101)).isEqualTo(-4);
        assertThat(weightLatency(5102)).isEqualTo(4);
    }

    private BigDecimal costOf(int modelId, int providerId) {
        return jdbc.queryForObject(
            "SELECT derived_cost_usd FROM model_provider WHERE model_id = ? AND provider_id = ?",
            BigDecimal.class, modelId, providerId);
    }

    private Integer weightLatency(int modelId) {
        return jdbc.queryForObject("SELECT weight_latency FROM models WHERE id = ?", Integer.class, modelId);
    }

    private Integer weightCost(int modelId) {
        return jdbc.queryForObject("SELECT weight_cost FROM models WHERE id = ?", Integer.class, modelId);
    }

    /** Poll a condition for up to 10 s: the re-derivation under test runs on the async executor. */
    private static void awaitUntil(BooleanSupplier condition) throws InterruptedException {
        long deadline = System.currentTimeMillis() + 10_000;
        while (!condition.getAsBoolean()) {
            if (System.currentTimeMillis() > deadline) {
                throw new AssertionError("condition not met within 10 s");
            }
            Thread.sleep(50);
        }
    }
}
