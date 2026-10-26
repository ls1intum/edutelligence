package de.tum.cit.aet.logos.logoswebservice.configuration;

import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import javax.sql.DataSource;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.client.HttpClientErrorException;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.nullValue;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.ArgumentMatchers.notNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import de.tum.cit.aet.logos.logoswebservice.configuration.service.LaneLockService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelCapabilitiesUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorModelSyncClient;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorNotificationService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorWorkerAdminClient;
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
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class ProviderControllerTest {

    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;
    @Autowired DataSource dataSource;
    @Autowired LaneLockService laneLockService;
    @MockitoBean JwtDecoder jwtDecoder;
    // Mocked so the price refresh triggered by connect_model_provider does not
    // reach the live litellm catalog during tests.
    @MockitoBean PriceUpdaterService priceUpdaterService;
    // Mocked so stopCalibration/calibrateUncalibrated tests never make a real
    // outbound call to an orchestrator — only the request-body binding into
    // OrchestratorWorkerAdminClient's int/String args is under test here.
    @MockitoBean OrchestratorWorkerAdminClient workerAdminClient;
    // Mocked so tests can assert what the endpoint announces to the
    // orchestrator instead of sending nothing (no orchestrator URL in tests).
    @MockitoBean OrchestratorNotificationService orchestratorNotificationService;
    // Mocked so the status endpoint is testable without an orchestrator URL.
    @MockitoBean OrchestratorModelSyncClient modelSyncClient;
    @MockitoBean ModelCapabilitiesUpdaterService modelCapabilitiesUpdaterService;

    @Test
    void getProviders_adminReturnsAllProviders() throws Exception {
        jdbc.update("UPDATE providers SET api_key = 'stored-provider-secret' WHERE id = 6001");
        mvc.perform(post("/logosdb/get_providers")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$[0].id").value(6001))
           .andExpect(jsonPath("$[0].name").value("openai-provider"))
           .andExpect(jsonPath("$[0].authentication_configured").doesNotExist())
           .andExpect(jsonPath("$[0].api_key").value("stored-provider-secret"));
    }

    @Test
    void getProviders_requiresAuthentication() throws Exception {
        mvc.perform(post("/logosdb/get_providers")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void getProviders_hidesCredentialsFromAuthorizedTeamMembers() throws Exception {
        jdbc.update("UPDATE providers SET api_key = 'stored-provider-secret' WHERE id = 6001");
        jdbc.update("INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (2001, 6001)");

        mvc.perform(post("/logosdb/get_providers")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0].id").value(6001))
           .andExpect(jsonPath("$[0].authentication_configured").doesNotExist())
           .andExpect(jsonPath("$[0].api_key").doesNotExist());
    }

    @Test
    void addProvider_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/add_provider")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"provider_name\":\"x\",\"base_url\":\"http://x\",\"provider_type\":\"cloud\",\"privacy_level\":\"LOCAL\",\"auth_name\":\"Auth\",\"auth_format\":\"Bearer {}\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void addProvider_logosAdminCreatesProvider() throws Exception {
        mvc.perform(post("/logosdb/add_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_name\":\"new-provider\",\"base_url\":\"http://example.com\","
                    + "\"provider_type\":\"cloud\",\"privacy_level\":\"LOCAL\","
                    + "\"auth_name\":\"Authorization\",\"auth_format\":\"Bearer {}\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Created Provider."))
           .andExpect(jsonPath("$['provider-id']").isNumber());
    }

    @Test
    void addProvider_logosnodeGeneratesApiKeyWhenAbsent() throws Exception {
        mvc.perform(post("/logosdb/add_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_name\":\"local-node\",\"base_url\":\"http://example.com\","
                    + "\"provider_type\":\"logosnode\",\"privacy_level\":\"LOCAL\","
                    + "\"auth_name\":\"\",\"auth_format\":\"{}\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Created Provider."))
           .andExpect(jsonPath("$.api_key")
               .value(org.hamcrest.Matchers.matchesPattern("[A-Za-z0-9_-]{64}")));
    }

    @Test
    void addProvider_logosnodeEchoesExplicitlyProvidedKey() throws Exception {
        mvc.perform(post("/logosdb/add_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_name\":\"local-node-2\",\"base_url\":\"http://example.com\","
                    + "\"provider_type\":\"logosnode\",\"privacy_level\":\"LOCAL\","
                    + "\"auth_name\":\"\",\"auth_format\":\"{}\",\"api_key\":\"my-shared-key\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.api_key").value("my-shared-key"));
    }

    @Test
    void addProvider_cloudDoesNotGenerateApiKey() throws Exception {
        mvc.perform(post("/logosdb/add_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_name\":\"cloud-p\",\"base_url\":\"http://example.com\","
                    + "\"provider_type\":\"cloud\",\"privacy_level\":\"CLOUD_IN_EU_BY_US_PROVIDER\","
                    + "\"auth_name\":\"Authorization\",\"auth_format\":\"Bearer {}\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.api_key").doesNotExist());
    }

    @Test
    void addProvider_rejectsDroppedOllamaType() throws Exception {
        mvc.perform(post("/logosdb/add_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_name\":\"ollama-provider\",\"base_url\":\"http://example.com\","
                    + "\"provider_type\":\"ollama\",\"privacy_level\":\"LOCAL\","
                    + "\"auth_name\":\"Authorization\",\"auth_format\":\"Bearer {}\"}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value(containsString("no longer supported")));
    }

    @Test
    void updateProvider_updatesName() throws Exception {
        mvc.perform(post("/logosdb/update_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"provider_name\":\"renamed-provider\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Updated Provider."));
    }

    @Test
    void deleteProvider_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/delete_provider")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void deleteProvider_logosAdminCanDelete() throws Exception {
        mvc.perform(post("/logosdb/delete_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Deleted Provider."));
    }

    @Test
    void deleteProvider_refusedWhileABatchStillRunsOrOwesItsSettlement() throws Exception {
        // The upstream job outlives the providers table: cascading the
        // ownership row away would make it unreachable and its spend
        // unbillable, so the deletion is refused until it is settled.
        jdbc.update(
            "INSERT INTO batch_objects (kind, upstream_id, provider_id, team_id, execution, status, created_at, updated_at) "
                + "VALUES ('batch', 'batch_delete_guard', 6001, 2001, 'provider', 'in_progress', now(), now())");
        try {
            mvc.perform(post("/logosdb/delete_provider")
                    .with(TestJwt.logosAdmin())
                    .contentType("application/json")
                    .content("{\"provider_id\":6001}"))
               .andExpect(status().isConflict())
               .andExpect(jsonPath("$.detail").value(containsString("not yet settled")));
        } finally {
            jdbc.update("DELETE FROM batch_objects WHERE upstream_id = 'batch_delete_guard'");
        }
    }

    @Test
    void deleteProvider_allowedOnceTheBatchesAreSettled() throws Exception {
        // A terminal, metered batch is safe to cascade away with the
        // provider: nothing runs on it any more and its spend is booked.
        jdbc.update(
            "INSERT INTO batch_objects (kind, upstream_id, provider_id, team_id, execution, status, settled_at, created_at, updated_at) "
                + "VALUES ('batch', 'batch_delete_settled', 6001, 2001, 'provider', 'completed', now(), now(), now())");
        try {
            mvc.perform(post("/logosdb/delete_provider")
                    .with(TestJwt.logosAdmin())
                    .contentType("application/json")
                    .content("{\"provider_id\":6001}"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$.result").value("Deleted Provider."));
        } finally {
            // The cascade removed the settled row with the provider, so this
            // only covers a failed run where the provider still exists.
            jdbc.update("DELETE FROM batch_objects WHERE upstream_id = 'batch_delete_settled'");
        }
    }

    @Test
    void deleteProvider_serializesWithAConcurrentBatchRegistration() throws Exception {
        // The count alone has a window: a registration could commit its
        // unsettled batch after the count returns zero and before the delete,
        // and the cascade would then erase its row while the upstream job
        // keeps running. The provider row lock closes the window — the
        // registration's FK check waits on the delete, and once the
        // registration is committed the count sees it and refuses.
        CountDownLatch registrationInFlight = new CountDownLatch(1);
        Thread inserter = new Thread(() -> {
            try (Connection conn = dataSource.getConnection()) {
                conn.setAutoCommit(false);
                try (PreparedStatement ps = conn.prepareStatement(
                    "INSERT INTO batch_objects (kind, upstream_id, provider_id, team_id, execution, status, created_at, updated_at) "
                        + "VALUES ('batch', 'batch_delete_race', 6001, 2001, 'provider', 'validating', now(), now())")) {
                    ps.executeUpdate();
                }
                registrationInFlight.countDown();
                // Hold the FK lock while the delete is in flight; only then
                // commit, so the delete is forced to wait and see the batch.
                Thread.sleep(1500);
                conn.commit();
            } catch (Exception ignored) {
                // The thread must not kill the test on the way down.
            }
        });
        inserter.start();
        assertTrue(registrationInFlight.await(10, TimeUnit.SECONDS), "the concurrent registration did not start");
        try {
            mvc.perform(post("/logosdb/delete_provider")
                    .with(TestJwt.logosAdmin())
                    .contentType("application/json")
                    .content("{\"provider_id\":6001}"))
               .andExpect(status().isConflict());
            // The provider survived with its batch: the ownership row (and
            // with it the billing state) is intact.
            assertEquals(1, jdbc.queryForObject(
                "SELECT count(*) FROM batch_objects WHERE upstream_id = 'batch_delete_race'", Integer.class));
        } finally {
            inserter.join(15_000);
            jdbc.update("DELETE FROM batch_objects WHERE upstream_id = 'batch_delete_race'");
        }
    }

    @Test
    void connectModelProvider_createsLink() throws Exception {
        mvc.perform(post("/logosdb/connect_model_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"model_id\":5002}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").isString());
    }

    @Test
    void connectModelProvider_refreshesPricesForTheLinkedModel() throws Exception {
        mvc.perform(post("/logosdb/connect_model_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"model_id\":5002}"))
           .andExpect(status().isOk());

        // Without this refresh a freshly linked cloud model kept reporting a
        // cost of zero until the next daily full refresh.
        verify(priceUpdaterService).updatePricesForModelAsync(5002);
        verify(modelCapabilitiesUpdaterService).updateCapabilitiesForModelAsync(5002, "gpt-3.5");
    }

    @Test
    void disconnectModelProvider_removesLink() throws Exception {
        mvc.perform(post("/logosdb/disconnect_model_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"model_id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Disconnected model from provider."));
    }

    @Test
    void getProviderModels_returnsModels() throws Exception {
        jdbc.update("UPDATE model_provider SET api_key = 'stored-model-secret' WHERE id = 7001");
        mvc.perform(post("/logosdb/get_provider_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$[0].model_id").value(5001))
           .andExpect(jsonPath("$[0].authentication_configured").doesNotExist())
           .andExpect(jsonPath("$[0].api_key").value("stored-model-secret"));
    }

    @Test
    void getProviderModels_requiresAuthentication() throws Exception {
        mvc.perform(post("/logosdb/get_provider_models")
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void getProviderModels_requiresAccessToTheRequestedProvider() throws Exception {
        mvc.perform(post("/logosdb/get_provider_models")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void getProviderModels_hidesCredentialsFromAuthorizedTeamMembers() throws Exception {
        jdbc.update("UPDATE model_provider SET api_key = 'stored-model-secret' WHERE id = 7001");
        jdbc.update("INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (2001, 6001)");

        mvc.perform(post("/logosdb/get_provider_models")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0].model_id").value(5001))
           .andExpect(jsonPath("$[0].authentication_configured").doesNotExist())
           .andExpect(jsonPath("$[0].api_key").doesNotExist());
    }

    @Test
    void getGeneralProviderStats_returnsCount() throws Exception {
        mvc.perform(post("/logosdb/get_general_provider_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.totalProviders").isNumber());
    }

    @Test
    void refreshModels_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/refresh_models")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
        verify(orchestratorNotificationService, never()).notifyRefresh(anyBoolean(), anyBoolean());
    }

    @Test
    void refreshModels_triggersCloudModelSync() throws Exception {
        when(orchestratorNotificationService.sendRefreshSync(false, true)).thenReturn(true);

        mvc.perform(post("/logosdb/refresh_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Model refresh triggered."));

        // syncCloudModels must be true: a plain pipeline refresh would leave
        // the upstream listings unread until the next 15-minute interval.
        verify(orchestratorNotificationService).sendRefreshSync(false, true);
    }

    @Test
    void refreshModels_reports503WhenTheOrchestratorCouldNotBeReached() throws Exception {
        // The mock's default false: the pass was never handed over, so a 200
        // would leave the UI polling a completion status that can never come.
        mvc.perform(post("/logosdb/refresh_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isServiceUnavailable())
           .andExpect(jsonPath("$.error").value(containsString("orchestrator")));
    }

    @Test
    void modelSyncStatus_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/model_sync_status")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void modelSyncStatus_reportsTheOrchestratorState() throws Exception {
        when(modelSyncClient.isSyncRunning()).thenReturn(true);

        mvc.perform(post("/logosdb/model_sync_status")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.running").value(true));
    }

    @Test
    void modelSyncStatus_reportsExplicitIdle() throws Exception {
        when(modelSyncClient.isSyncRunning()).thenReturn(false);

        mvc.perform(post("/logosdb/model_sync_status")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.running").value(false));
    }

    @Test
    void modelSyncStatus_reportsUnknownWhenTheStatusCouldNotBeRead() throws Exception {
        // null: the orchestrator did not answer. The UI settles an accepted
        // refresh only on an explicit false, so the endpoint has to be able
        // to express "unknown" — collapsing it to false would end the wait
        // on a transient failure.
        when(modelSyncClient.isSyncRunning()).thenReturn(null);

        mvc.perform(post("/logosdb/model_sync_status")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.running", nullValue()));
    }

    @Test
    void addLane_rejectsNonAdmin() throws Exception {
        mvc.perform(post("/logosdb/providers/logosnode/lanes/add")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane\":{\"model\":\"llama3\"}}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void addLane_requiresProviderAndLane() throws Exception {
        mvc.perform(post("/logosdb/providers/logosnode/lanes/add")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("provider_id and lane are required"));

        mvc.perform(post("/logosdb/providers/logosnode/lanes/add")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"lane\":{\"model\":\"llama3\"}}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("provider_id and lane are required"));
    }

    @Test
    void sleepLane_rejectsNonAdmin() throws Exception {
        mvc.perform(post("/logosdb/providers/logosnode/lanes/sleep")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void sleepLane_requiresProviderAndLane() throws Exception {
        mvc.perform(post("/logosdb/providers/logosnode/lanes/sleep")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("provider_id and lane_id are required"));

        mvc.perform(post("/logosdb/providers/logosnode/lanes/sleep")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("provider_id and lane_id are required"));
    }

    @Test
    void wakeLane_rejectsNonAdmin() throws Exception {
        mvc.perform(post("/logosdb/providers/logosnode/lanes/wake")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void wakeLane_requiresProviderAndLane() throws Exception {
        mvc.perform(post("/logosdb/providers/logosnode/lanes/wake")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("provider_id and lane_id are required"));

        mvc.perform(post("/logosdb/providers/logosnode/lanes/wake")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("provider_id and lane_id are required"));
    }

    @Test
    void drainLane_rejectsNonAdmin() throws Exception {
        mvc.perform(post("/logosdb/providers/logosnode/lanes/drain")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void drainLane_requiresProviderAndLane() throws Exception {
        mvc.perform(post("/logosdb/providers/logosnode/lanes/drain")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("provider_id and lane_id are required"));

        mvc.perform(post("/logosdb/providers/logosnode/lanes/drain")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("provider_id and lane_id are required"));
    }

    @Test
    void drainLane_forwardsSnakeCaseBodyToWorkerAdminClient() throws Exception {
        when(workerAdminClient.drainLane(6001, "planner-Qwen_Qwen3.8-27B"))
            .thenReturn(ResponseEntity.ok(Map.of("status", "slept")));

        mvc.perform(post("/logosdb/providers/logosnode/lanes/drain")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane_id\":\"planner-Qwen_Qwen3.8-27B\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.status").value("slept"));

        verify(workerAdminClient).drainLane(6001, "planner-Qwen_Qwen3.8-27B");
    }

    @Test
    void stopCalibration_bindsSnakeCaseProviderIdFromRequestBody() throws Exception {
        // StopCalibrationRequestDTO.providerId() must actually be populated
        // from the UI's snake_case "provider_id" body — a prior review
        // thread questioned whether the app's custom ObjectMapper bean
        // (JacksonConfig) still honours spring.jackson.property-naming-
        // strategy=SNAKE_CASE. Asserting the int reaching
        // OrchestratorWorkerAdminClient proves the binding, independent of
        // internal Spring wiring details.
        when(workerAdminClient.stopCalibration(6001))
            .thenReturn(ResponseEntity.ok(Map.of("was_active", false)));

        mvc.perform(post("/logosdb/providers/logosnode/stop_calibration")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.was_active").value(false));

        verify(workerAdminClient).stopCalibration(eq(6001));
    }

    @Test
    void stopCalibration_requiresProviderId() throws Exception {
        mvc.perform(post("/logosdb/providers/logosnode/stop_calibration")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("provider_id is required"));
    }

    // ------------------------------------------------------------ maintenance slot

    @Test
    void maintenanceEndpoints_requireLogosAdmin() throws Exception {
        mvc.perform(get("/logosdb/maintenance")
                .with(TestJwt.adminUser()))
           .andExpect(status().isForbidden());
        mvc.perform(post("/logosdb/maintenance/release_calibration")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"claim_token\":\"t\"}"))
           .andExpect(status().isForbidden());
        verify(workerAdminClient, never()).maintenanceStatus();
        verify(workerAdminClient, never()).releaseCalibrationClaim(anyInt(), anyString());
    }

    @Test
    void maintenanceStatus_proxiesTheOrchestratorView() throws Exception {
        when(workerAdminClient.maintenanceStatus())
            .thenReturn(ResponseEntity.ok(Map.of("free", false, "limit", 1)));

        mvc.perform(get("/logosdb/maintenance")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.free").value(false))
           .andExpect(jsonPath("$.limit").value(1));
    }

    @Test
    void maintenanceStatus_reportsAnUnreachableOrchestrator() throws Exception {
        when(workerAdminClient.maintenanceStatus())
            .thenThrow(new IllegalStateException("Orchestrator URL or internal secret not configured"));

        mvc.perform(get("/logosdb/maintenance")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isServiceUnavailable())
           .andExpect(jsonPath("$.error").value("Orchestrator URL or internal secret not configured"));
    }

    @Test
    void releaseCalibrationClaim_requiresProviderAndToken() throws Exception {
        mvc.perform(post("/logosdb/maintenance/release_calibration")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("provider_id and claim_token are required"));
        verify(workerAdminClient, never()).releaseCalibrationClaim(anyInt(), anyString());
    }

    @Test
    void releaseCalibrationClaim_forwardsAndRecordsTheRelease() throws Exception {
        jdbc.update("DELETE FROM audit_log WHERE action = 'provider.calibration_claim_released'");
        when(workerAdminClient.releaseCalibrationClaim(6001, "claim-1"))
            .thenReturn(ResponseEntity.ok(Map.of("released", true, "forced", true)));

        mvc.perform(post("/logosdb/maintenance/release_calibration")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"claim_token\":\"claim-1\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.forced").value(true));

        verify(workerAdminClient).releaseCalibrationClaim(6001, "claim-1");
        Map<String, Object> entry = jdbc.queryForMap(
            "SELECT target_type, target_id, CAST(before_state AS text) AS before_state, "
                + "CAST(after_state AS text) AS after_state FROM audit_log "
                + "WHERE action = 'provider.calibration_claim_released'");
        assertEquals("provider", entry.get("target_type"));
        assertEquals("6001", entry.get("target_id"));
        assertTrue(entry.get("before_state").toString().contains("claim-1"));
        assertTrue(entry.get("after_state").toString().contains("\"confirmed_by_worker\": false"));
    }

    @Test
    void releaseCalibrationClaim_passesARefusalThroughWithoutAuditEntry() throws Exception {
        jdbc.update("DELETE FROM audit_log WHERE action = 'provider.calibration_claim_released'");
        when(workerAdminClient.releaseCalibrationClaim(6001, "claim-1"))
            .thenThrow(HttpClientErrorException.create(HttpStatus.CONFLICT, "Conflict", HttpHeaders.EMPTY,
                "{\"detail\":\"The worker still reports a calibration session\"}".getBytes(StandardCharsets.UTF_8),
                StandardCharsets.UTF_8));

        mvc.perform(post("/logosdb/maintenance/release_calibration")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"claim_token\":\"claim-1\"}"))
           .andExpect(status().isConflict())
           .andExpect(jsonPath("$.detail").value("The worker still reports a calibration session"));

        assertEquals(0, jdbc.queryForObject(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'provider.calibration_claim_released'", Integer.class));
    }

    @Test
    void releaseRecovery_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/maintenance/release_recovery")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"model_provider_id\":31}"))
           .andExpect(status().isForbidden());
        mvc.perform(post("/logosdb/maintenance/release_recovery")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"model_provider_id\":31,\"force\":true}"))
           .andExpect(status().isForbidden());
        verify(workerAdminClient, never()).releaseRecovery(anyInt(), anyBoolean());
    }

    @Test
    void releaseRecovery_requiresTheDeployment() throws Exception {
        mvc.perform(post("/logosdb/maintenance/release_recovery")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"force\":true}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("model_provider_id is required"));
        verify(workerAdminClient, never()).releaseRecovery(anyInt(), anyBoolean());
    }

    @Test
    void releaseRecovery_forwardsAndRecordsTheRelease() throws Exception {
        jdbc.update("DELETE FROM audit_log WHERE action = 'provider.nightly_recovery_released'");
        when(workerAdminClient.releaseRecovery(31, false))
            .thenReturn(ResponseEntity.ok(Map.of("released", true, "forced", false)));

        mvc.perform(post("/logosdb/maintenance/release_recovery")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_provider_id\":31}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.forced").value(false));

        verify(workerAdminClient).releaseRecovery(31, false);
        Map<String, Object> entry = jdbc.queryForMap(
            "SELECT target_type, target_id, CAST(after_state AS text) AS after_state FROM audit_log "
                + "WHERE action = 'provider.nightly_recovery_released'");
        assertEquals("model_provider", entry.get("target_type"));
        assertEquals("31", entry.get("target_id"));
        assertTrue(entry.get("after_state").toString().contains("\"forced\": false"));
    }

    @Test
    void releaseRecovery_forwardsForce() throws Exception {
        jdbc.update("DELETE FROM audit_log WHERE action = 'provider.nightly_recovery_released'");
        when(workerAdminClient.releaseRecovery(31, true))
            .thenReturn(ResponseEntity.ok(Map.of("released", true, "forced", true)));

        mvc.perform(post("/logosdb/maintenance/release_recovery")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_provider_id\":31,\"force\":true}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.forced").value(true));

        verify(workerAdminClient).releaseRecovery(31, true);
        String after = jdbc.queryForObject(
            "SELECT CAST(after_state AS text) FROM audit_log WHERE action = 'provider.nightly_recovery_released'",
            String.class);
        assertTrue(after.contains("\"forced\": true"));
    }

    @Test
    void releaseRecovery_passesARefusalThroughWithoutAuditEntry() throws Exception {
        jdbc.update("DELETE FROM audit_log WHERE action = 'provider.nightly_recovery_released'");
        when(workerAdminClient.releaseRecovery(31, false))
            .thenThrow(HttpClientErrorException.create(HttpStatus.CONFLICT, "Conflict", HttpHeaders.EMPTY,
                "{\"detail\":\"The lane does not run its original settings yet\"}".getBytes(StandardCharsets.UTF_8),
                StandardCharsets.UTF_8));

        mvc.perform(post("/logosdb/maintenance/release_recovery")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_provider_id\":31}"))
           .andExpect(status().isConflict())
           .andExpect(jsonPath("$.detail").value("The lane does not run its original settings yet"));

        assertEquals(0, jdbc.queryForObject(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'provider.nightly_recovery_released'", Integer.class));
    }

    // ------------------------------------------------------------ lane locks

    @Test
    void laneLocks_requireLogosAdmin() throws Exception {
        mvc.perform(get("/logosdb/providers/logosnode/lanes/locks")
                .with(TestJwt.testUser()))
           .andExpect(status().isForbidden());
        mvc.perform(post("/logosdb/providers/logosnode/lanes/lock")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isForbidden());
        mvc.perform(post("/logosdb/providers/logosnode/lanes/unlock")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isForbidden());
        assertEquals(0, lockCount());
    }

    @Test
    void lockLane_requiresProviderAndLane() throws Exception {
        mvc.perform(post("/logosdb/providers/logosnode/lanes/lock")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("provider_id and lane_id are required"));
        mvc.perform(post("/logosdb/providers/logosnode/lanes/unlock")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void lockLane_storesTheLockAndListsIt() throws Exception {
        jdbc.update("DELETE FROM audit_log WHERE target_type = 'lane'");
        mvc.perform(post("/logosdb/providers/logosnode/lanes/lock")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane_id\":\"lane-1\",\"model_name\":\"embed-model\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.provider_id").value(6001))
           .andExpect(jsonPath("$.lane_id").value("lane-1"))
           .andExpect(jsonPath("$.model_name").value("embed-model"))
           .andExpect(jsonPath("$.locked_at").exists());

        mvc.perform(get("/logosdb/providers/logosnode/lanes/locks")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0].lane_id").value("lane-1"))
           .andExpect(jsonPath("$[0].model_name").value("embed-model"));

        Integer audited = jdbc.queryForObject(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'lane.locked' AND target_id = '6001/lane-1'",
            Integer.class);
        assertEquals(1, audited);
    }

    @Test
    void lockAndUnlock_pushTheChangeToTheOrchestrator() throws Exception {
        mvc.perform(post("/logosdb/providers/logosnode/lanes/lock")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isOk());
        verify(orchestratorNotificationService).notifyLaneLock(eq(6001), eq("lane-1"), eq(true), anyLong(), isNull());

        mvc.perform(post("/logosdb/providers/logosnode/lanes/unlock")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isOk());
        verify(orchestratorNotificationService).notifyLaneLock(eq(6001), eq("lane-1"), eq(false), anyLong());

        // Unlocking a lane that is not locked changes nothing and pushes nothing.
        mvc.perform(post("/logosdb/providers/logosnode/lanes/unlock")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isOk());
        verify(orchestratorNotificationService, times(1)).notifyLaneLock(eq(6001), eq("lane-1"), eq(false), anyLong());
    }

    @Test
    void everyLockChange_carriesAHigherRevisionForTheLane() {
        jdbc.update("DELETE FROM audit_log WHERE target_type = 'lane'");
        laneLockService.lock(null, 6001, "lane-1", "embed-model");
        long locked = revision();
        laneLockService.unlock(6001, "lane-1");
        long unlocked = revision();
        laneLockService.lock(null, 6001, "lane-1", null);
        long relocked = revision();

        assertTrue(locked < unlocked && unlocked < relocked);
        org.mockito.InOrder order = org.mockito.Mockito.inOrder(orchestratorNotificationService);
        order.verify(orchestratorNotificationService).notifyLaneLock(6001, "lane-1", true, locked, null);
        order.verify(orchestratorNotificationService).notifyLaneLock(6001, "lane-1", false, unlocked);
        order.verify(orchestratorNotificationService).notifyLaneLock(6001, "lane-1", true, relocked, null);
        // A relock after an unlock is a new lock, not a refresh of the old one.
        assertEquals(1, lockCount());
        assertEquals(2, auditCount("lane.locked"));
    }

    @Test
    void lockLane_isIdempotent() throws Exception {
        jdbc.update("DELETE FROM audit_log WHERE target_type = 'lane'");
        for (int i = 0; i < 2; i++) {
            mvc.perform(post("/logosdb/providers/logosnode/lanes/lock")
                    .with(TestJwt.logosAdmin())
                    .contentType("application/json")
                    .content("{\"provider_id\":6001,\"lane_id\":\"lane-1\",\"model_name\":\"embed-model\"}"))
               .andExpect(status().isOk());
        }
        assertEquals(1, lockCount());
        // The second lock changed nothing, so the trail holds one entry.
        Integer audited = jdbc.queryForObject(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'lane.locked' AND target_id = '6001/lane-1'",
            Integer.class);
        assertEquals(1, audited);
    }

    @Test
    void workerLock_isAuditedAsAWorkerChange() {
        jdbc.update("DELETE FROM audit_log WHERE target_type IN ('lane', 'worker')");
        laneLockService.lock(null, 6001, LaneLockService.WORKER_LANE_ID, null);
        laneLockService.unlock(6001, LaneLockService.WORKER_LANE_ID);

        assertEquals(1, jdbc.queryForObject(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'worker.locked' AND target_id = '6001'", Integer.class));
        assertEquals(1, jdbc.queryForObject(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'worker.unlocked' AND target_id = '6001'", Integer.class));
        assertEquals(0, auditCount("lane.locked"));
    }

    @Test
    void newLock_startsWithoutTheRestoreRecordOfAnEarlierOne() {
        laneLockService.lock(null, 6001, "lane-1", "embed-model");
        jdbc.update("UPDATE lane_locks SET restore_lanes = '{\"lane-1\": {\"sleeping\": false}}' "
            + "WHERE provider_id = 6001 AND lane_id = 'lane-1'");

        // Locking a locked lane again keeps what the planner recorded, and
        // the push carries it, so the planner never holds an older record.
        laneLockService.lock(null, 6001, "lane-1", "embed-model");
        assertEquals(1, restoreRecords());
        verify(orchestratorNotificationService).notifyLaneLock(eq(6001), eq("lane-1"), eq(true), anyLong(), notNull());

        laneLockService.unlock(6001, "lane-1");
        laneLockService.lock(null, 6001, "lane-1", "embed-model");
        assertEquals(0, restoreRecords());
    }

    private int restoreRecords() {
        return jdbc.queryForObject(
            "SELECT COUNT(*) FROM lane_locks WHERE restore_lanes IS NOT NULL", Integer.class);
    }

    @Test
    void concurrentFirstLocksAndUnlocks_recordOneTransitionEach() throws Exception {
        jdbc.update("DELETE FROM audit_log WHERE target_type = 'lane'");
        runTogether(() -> laneLockService.lock(null, 6001, "lane-1", "embed-model"));
        assertEquals(1, lockCount());
        assertEquals(1, auditCount("lane.locked"));

        runTogether(() -> laneLockService.unlock(6001, "lane-1"));
        assertEquals(0, lockCount());
        assertEquals(1, auditCount("lane.unlocked"));
    }

    /** Runs the action on several threads released at the same instant. */
    private void runTogether(Runnable action) throws Exception {
        int threads = 4;
        CountDownLatch start = new CountDownLatch(1);
        java.util.concurrent.ExecutorService pool = java.util.concurrent.Executors.newFixedThreadPool(threads);
        try {
            java.util.List<java.util.concurrent.Future<?>> futures = new java.util.ArrayList<>();
            for (int i = 0; i < threads; i++) {
                futures.add(pool.submit(() -> {
                    start.await();
                    action.run();
                    return null;
                }));
            }
            start.countDown();
            for (java.util.concurrent.Future<?> f : futures) {
                f.get(30, TimeUnit.SECONDS);
            }
        } finally {
            pool.shutdownNow();
        }
    }

    private int auditCount(String action) {
        Integer n = jdbc.queryForObject(
            "SELECT COUNT(*) FROM audit_log WHERE action = ? AND target_id = '6001/lane-1'", Integer.class, action);
        return n == null ? 0 : n;
    }

    @Test
    void lockLane_unknownProviderIsNotFound() throws Exception {
        mvc.perform(post("/logosdb/providers/logosnode/lanes/lock")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":999999,\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isNotFound());
        assertEquals(0, lockCount());
    }

    @Test
    void unlockLane_removesTheLockAndIsIdempotent() throws Exception {
        jdbc.update("INSERT INTO lane_locks (provider_id, lane_id, model_name) VALUES (6001, 'lane-1', 'm')");

        mvc.perform(post("/logosdb/providers/logosnode/lanes/unlock")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.unlocked").value(true));
        assertEquals(0, lockCount());

        mvc.perform(post("/logosdb/providers/logosnode/lanes/unlock")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"lane_id\":\"lane-1\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.unlocked").value(false));
    }

    @Test
    void laneLock_isRemovedWithItsProvider() throws Exception {
        jdbc.update("INSERT INTO lane_locks (provider_id, lane_id) VALUES (6001, 'lane-1')");
        jdbc.update("DELETE FROM model_provider WHERE provider_id = 6001");
        jdbc.update("DELETE FROM providers WHERE id = 6001");
        assertEquals(0, lockCount());
    }

    private long revision() {
        Long n = jdbc.queryForObject(
            "SELECT revision FROM lane_locks WHERE provider_id = 6001 AND lane_id = 'lane-1'", Long.class);
        return n == null ? -1 : n;
    }

    private int lockCount() {
        Integer n = jdbc.queryForObject("SELECT COUNT(*) FROM lane_locks WHERE locked", Integer.class);
        return n == null ? 0 : n;
    }
}
