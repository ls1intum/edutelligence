package de.tum.cit.aet.logos.logoswebservice.configuration;

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

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;

import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;
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
    @MockitoBean JwtDecoder jwtDecoder;
    // Mocked so the price refresh triggered by connect_model_provider does not
    // reach the live litellm catalog during tests.
    @MockitoBean PriceUpdaterService priceUpdaterService;

    @Test
    void getProviders_adminReturnsAllProviders() throws Exception {
        mvc.perform(post("/logosdb/get_providers")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$[0].id").value(6001))
           .andExpect(jsonPath("$[0].name").value("openai-provider"));
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
    void connectModelProvider_createsLink() throws Exception {
        mvc.perform(post("/logosdb/connect_model_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"model_id\":5002}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").isString());
    }

    @Test
    void connectModelProvider_triggersDerivationAfterPriceRefresh() throws Exception {
        mvc.perform(post("/logosdb/connect_model_provider")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001,\"model_id\":5002}"))
           .andExpect(status().isOk());

        // Without this refresh a freshly linked cloud model kept reporting a
        // cost of zero until the next daily full refresh. The derivation runs
        // asynchronously and only after the catalogue price refresh committed,
        // so wait for the price refresh to be observed.
        verify(priceUpdaterService, timeout(5000)).updatePricesForModel(eq(5002), anyString());
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
        mvc.perform(post("/logosdb/get_provider_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_id\":6001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$[0].model_id").value(5001));
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
}
