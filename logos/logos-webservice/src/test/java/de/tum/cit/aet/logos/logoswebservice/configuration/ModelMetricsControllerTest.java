package de.tum.cit.aet.logos.logoswebservice.configuration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelMetricsService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorNotificationService;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
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
    JdbcTemplate jdbc;
    @Autowired
    ModelRepository modelRepository;
    @MockitoBean
    JwtDecoder jwtDecoder;
    // Mocked so the price refresh the derivation waits for never reaches the
    // live litellm catalog; tests install prices via the mock's answer.
    @MockitoBean
    PriceUpdaterService priceUpdaterService;
    @MockitoBean
    OrchestratorNotificationService orchestratorNotificationService;

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
    void steadyStateDerivation_isNoOpWithoutNotification() {
        // First run moves the weights from their seed values onto the derived
        // scale (and notifies). Clear the bookkeeping so the assertion below
        // only covers the steady-state second run - the startup @Scheduled run
        // may otherwise have raced with the seed and poked the mock too.
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
}
