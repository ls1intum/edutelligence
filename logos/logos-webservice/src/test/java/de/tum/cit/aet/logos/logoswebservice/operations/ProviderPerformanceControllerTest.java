package de.tum.cit.aet.logos.logoswebservice.operations;

import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.ResponseEntity;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.mockito.Mockito.when;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorWorkerAdminClient;

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
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-operations.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-operations.sql", "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class ProviderPerformanceControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;
    @MockitoBean OrchestratorWorkerAdminClient orchestratorWorkerAdminClient;

    @Test
    void providerPerformance_returnsMetricsPerProviderModelPair() throws Exception {
        mvc.perform(post("/logosdb/provider_performance")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.from").isString())
           .andExpect(jsonPath("$.to").isString())
           .andExpect(jsonPath("$.pairs.length()").value(1))
           .andExpect(jsonPath("$.pairs[0].provider_id").value(6001))
           .andExpect(jsonPath("$.pairs[0].provider_name").value("openai-provider"))
           .andExpect(jsonPath("$.pairs[0].model_id").value(5001))
           .andExpect(jsonPath("$.pairs[0].model_name").value("gpt-4"))
           .andExpect(jsonPath("$.pairs[0].request_count").value(2))
           .andExpect(jsonPath("$.pairs[0].successful_request_count").value(2))
           .andExpect(jsonPath("$.pairs[0].success_rate").value(1.0))
           .andExpect(jsonPath("$.pairs[0].cold_start_count").value(1))
           .andExpect(jsonPath("$.pairs[0].cold_start_rate").value(0.5))
           .andExpect(jsonPath("$.pairs[0].ttft_ms.p50").value(45000.0))
           .andExpect(jsonPath("$.pairs[0].ttft_ms.p95").value(58500.0))
           .andExpect(jsonPath("$.pairs[0].ttft_ms.p100").value(60000.0))
           .andExpect(jsonPath("$.pairs[0].tpot_ms.p50").value(30000.0))
           .andExpect(jsonPath("$.pairs[0].tpot_ms.p95").value(30000.0))
           .andExpect(jsonPath("$.pairs[0].tpot_ms.p100").value(30000.0))
           .andExpect(jsonPath("$.pairs[0].ttlt_ms.p50").value(120000.0))
           .andExpect(jsonPath("$.pairs[0].ttlt_ms.p95").value(120000.0))
           .andExpect(jsonPath("$.pairs[0].ttlt_ms.p100").value(120000.0))
           .andExpect(jsonPath("$.pairs[0].devices").doesNotExist())
           .andExpect(jsonPath("$.pairs[0].available_vram_mb").doesNotExist());
    }

    @Test
    void providerPerformance_filtersByProviderAndModel() throws Exception {
        mvc.perform(post("/logosdb/provider_performance")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"model_id\":5002}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.pairs").isEmpty());
    }

    @Test
    void providerPerformance_rejectsInvalidTimeRange() throws Exception {
        mvc.perform(post("/logosdb/provider_performance")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"from\":\"2026-07-12T12:00:00Z\",\"to\":\"2026-07-12T11:00:00Z\"}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("from must be before to"));
    }

    @Test
    void providerPerformance_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/provider_performance")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void modelBenchmarks_returnsStoredGuideLlmSummaryForModel() throws Exception {
        mvc.perform(post("/logosdb/model_benchmarks")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.benchmarks.length()").value(1))
           .andExpect(jsonPath("$.benchmarks[0].model_provider_id").value(7001))
           .andExpect(jsonPath("$.benchmarks[0].provider_name").value("openai-provider"))
           .andExpect(jsonPath("$.benchmarks[0].model_name").value("gpt-4"))
           .andExpect(jsonPath("$.benchmarks[0].configuration.tool").value("guidellm"))
           .andExpect(jsonPath("$.benchmarks[0].dataset").value("openai/gsm8k"))
           .andExpect(jsonPath("$.benchmarks[0].sample_size").value(100))
           .andExpect(jsonPath("$.benchmarks[0].metrics.request_rate").value(2.5))
           .andExpect(jsonPath("$.benchmarks[0].metrics.request_latency_ms.p95").value(690.0))
           .andExpect(jsonPath("$.benchmarks[0].recorded_at").value("2026-08-24T12:00:00Z"))
           .andExpect(jsonPath("$.pairs.length()").value(1))
           .andExpect(jsonPath("$.pairs[0].model_provider_id").value(7001))
           .andExpect(jsonPath("$.pairs[0].endpoint_configured").value(true))
           .andExpect(jsonPath("$.runs").isEmpty());
    }

    @Test
    void modelBenchmarks_rejectsMissingModelId() throws Exception {
        mvc.perform(post("/logosdb/model_benchmarks")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("model_id must be a positive integer"));
    }

    @Test
    void importModelBenchmark_storesSuccessfulGuideLlmSummary() throws Exception {
        mvc.perform(post("/logosdb/model_benchmarks/import")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("""
                    {
                      "model_provider_id": 7001,
                      "configuration": {"tool":"guidellm","profile":{"kind":"sweep"}},
                      "dataset": "openai/gsm8k",
                      "sample_size": 50,
                      "metrics": {
                        "request_totals": {"successful":50,"incomplete":0,"errored":0,"total":50},
                        "time_to_first_token_ms": {"successful":{"p50":120.0,"p95":250.0}}
                      },
                      "recorded_at": "2026-08-25T10:00:00Z"
                    }
                    """))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.stored").value(true));

        mvc.perform(post("/logosdb/model_benchmarks")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.benchmarks.length()").value(2))
           .andExpect(jsonPath("$.benchmarks[0].sample_size").value(50))
           .andExpect(jsonPath("$.benchmarks[0].configuration.tool").value("guidellm"));
    }

    @Test
    void importModelBenchmark_rejectsFailedGuideLlmSummary() throws Exception {
        mvc.perform(post("/logosdb/model_benchmarks/import")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("""
                    {
                      "model_provider_id": 7001,
                      "configuration": {"tool":"guidellm"},
                      "dataset": "openai/gsm8k",
                      "sample_size": 50,
                      "metrics": {
                        "request_totals": {"successful":49,"incomplete":0,"errored":1,"total":50}
                      }
                    }
                    """))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error")
               .value("Only successful GuideLLM benchmark summaries are stored"));
    }

    @Test
    void runModelBenchmark_forwardsFixedSmallRunToOrchestrator() throws Exception {
        when(orchestratorWorkerAdminClient.startModelBenchmark(7001, 5, 512))
            .thenReturn(ResponseEntity.accepted().body(Map.of(
                "job_id", 42,
                "status", "pending",
                "model_provider_id", 7001
            )));

        mvc.perform(post("/logosdb/model_benchmarks/run")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_provider_id\":7001,\"sample_size\":5,\"max_output_tokens\":512}"))
           .andExpect(status().isAccepted())
           .andExpect(jsonPath("$.job_id").value(42))
           .andExpect(jsonPath("$.status").value("pending"));
    }
}
