package de.tum.cit.aet.logos.logoswebservice.operations;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;

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
}
