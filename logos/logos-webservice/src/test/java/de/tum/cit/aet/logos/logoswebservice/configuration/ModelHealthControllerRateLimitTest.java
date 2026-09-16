package de.tum.cit.aet.logos.logoswebservice.configuration;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.context.jdbc.SqlMergeMode;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorModelHealthClient;

/**
 * A leaked API key can otherwise be tested for validity against
 * /logosdb/get_model_health indefinitely; see issue: rate-limit publicly
 * reachable and unauthenticated endpoints.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    "logos.auth.roles.logos-admin=itg-admin",
    "logos.auth.roles.app-admin=chair-member",
    "logos.auth.sync-debounce-minutes=5",
    "logos.rate-limiting.enabled=true",
    "logos.rate-limiting.auth-failure-requests-per-minute=2"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class ModelHealthControllerRateLimitTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;
    @MockitoBean OrchestratorModelHealthClient modelHealthClient;

    @Test
    void repeatedFailedAuthFromOneAddressIsRateLimited() throws Exception {
        for (int i = 0; i < 2; i++) {
            mvc.perform(post("/logosdb/get_model_health")
                    .header("logos_key", "not-a-real-key")
                    .contentType("application/json")
                    .content("{}"))
               .andExpect(status().isUnauthorized());
        }

        // Successful auth is never exercised here — the budget is exhausted
        // entirely by the failure path — so the third failed attempt is the
        // one that trips the limit.
        mvc.perform(post("/logosdb/get_model_health")
                .header("logos_key", "not-a-real-key")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isTooManyRequests())
           .andExpect(header().string("Retry-After", "60"));
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        "INSERT INTO team_model_permissions (team_id, model_id) VALUES (2001, 5001)",
        "INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (2001, 6001)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void successfulAuthReleasesTheReservedSlot() throws Exception {
        when(modelHealthClient.getModelHealth()).thenReturn(List.of(Map.of("name", "gpt-4", "status", "UP")));

        // Each successful call reserves-then-releases its slot, so many more
        // than the configured limit must succeed without ever tripping 429.
        for (int i = 0; i < 5; i++) {
            mvc.perform(post("/logosdb/get_model_health")
                    .header("logos_key", "dev-key-1")
                    .contentType("application/json")
                    .content("{}"))
               .andExpect(status().isOk());
        }
    }
}
