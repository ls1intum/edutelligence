package de.tum.cit.aet.logos.logoswebservice.configuration;

import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorModelHealthClient;

/**
 * Regression for a review finding on the rate-limit fix in issue "Rate-limit publicly reachable and
 * unauthenticated endpoints": the auth-failure reservation used to be released only after
 * {@code OrchestratorModelHealthClient.getModelHealth()} returned, so a single slow (but valid) request could
 * hold its slot for as long as that downstream call was in flight — starving a second, otherwise independent
 * valid request of budget it should never have needed to compete for. The limit here is 1, so a second request
 * succeeding while the first is still blocked in its downstream call is only possible if the fix (release the
 * moment the key is known valid, before calling out) is in place.
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
    "logos.rate-limiting.auth-failure-requests-per-minute=1"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
@Sql(statements = {
    "INSERT INTO team_model_permissions (team_id, model_id) VALUES (2001, 5001)",
    "INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (2001, 6001)"
}, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
class ModelHealthControllerReleaseTimingTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;
    @MockitoBean OrchestratorModelHealthClient modelHealthClient;

    @Test
    void aSecondValidRequestSucceedsWhileTheFirstIsStillBlockedDownstream() throws Exception {
        CountDownLatch reachedDownstream = new CountDownLatch(1);
        CountDownLatch releaseDownstream = new CountDownLatch(1);
        when(modelHealthClient.getModelHealth()).thenAnswer(invocation -> {
            reachedDownstream.countDown();
            releaseDownstream.await(5, TimeUnit.SECONDS);
            return List.of(Map.of("name", "gpt-4", "status", "UP"));
        });

        ExecutorService pool = Executors.newSingleThreadExecutor();
        try {
            Future<Integer> first = pool.submit(() -> mvc.perform(post("/logosdb/get_model_health")
                    .header("logos_key", "dev-key-1")
                    .contentType("application/json")
                    .content("{}"))
                .andReturn().getResponse().getStatus());

            // The first request has passed authentication and reached the blocked downstream call — with the
            // configured limit of 1, its slot is only available again if it was released before that call, not
            // after it returns.
            assertTrue(reachedDownstream.await(5, TimeUnit.SECONDS));

            int secondStatus = mvc.perform(post("/logosdb/get_model_health")
                    .header("logos_key", "dev-key-1")
                    .contentType("application/json")
                    .content("{}"))
                .andReturn().getResponse().getStatus();
            assertEquals(200, secondStatus);

            releaseDownstream.countDown();
            assertEquals(200, first.get(5, TimeUnit.SECONDS).intValue());
        }
        finally {
            pool.shutdownNow();
        }
    }
}
