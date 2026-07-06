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
}
