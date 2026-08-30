package de.tum.cit.aet.logos.logoswebservice.configuration;

import java.util.LinkedHashMap;
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
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorModelHealthClient;

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
class ModelHealthControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;
    @MockitoBean OrchestratorModelHealthClient modelHealthClient;

    private static Map<String, Object> entry(String name, String status) {
        Map<String, Object> model = new LinkedHashMap<>();
        model.put("name", name);
        model.put("status", status);
        return model;
    }

    private void mockHealth() {
        when(modelHealthClient.getModelHealth()).thenReturn(List.of(
            entry("gpt-4", "UP"),
            entry("gpt-3.5", "DOWN")
        ));
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        "INSERT INTO team_model_permissions (team_id, model_id) VALUES (2001, 5001)",
        "INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (2001, 6001)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void keyWithTeamAccess_seesOnlyAssignedModels() throws Exception {
        mockHealth();

        // dev-key-1 belongs to team 2001 and does not use custom permissions.
        mvc.perform(post("/logosdb/get_model_health")
                .header("logos_key", "dev-key-1")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.models.length()").value(1))
           .andExpect(jsonPath("$.models[0].name").value("gpt-4"))
           .andExpect(jsonPath("$.models[0].status").value("UP"));
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        "UPDATE api_keys SET use_custom_permissions = true WHERE id = 3001",
        "INSERT INTO api_key_model_permissions (api_key_id, model_id) VALUES (3001, 5001)",
        "INSERT INTO api_key_provider_permissions (api_key_id, provider_id) VALUES (3001, 6001)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void keyWithCustomPermissions_usesKeyPermissionsInsteadOfTeam() throws Exception {
        mockHealth();

        // Team 2001 has no team permissions; dev-key-1's own permissions grant gpt-4.
        mvc.perform(post("/logosdb/get_model_health")
                .header("logos_key", "dev-key-1")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.models.length()").value(1))
           .andExpect(jsonPath("$.models[0].name").value("gpt-4"));

        // admin-key-1 shares the team but has no custom permissions and no team
        // grants either, so it sees nothing.
        mvc.perform(post("/logosdb/get_model_health")
                .header("logos_key", "admin-key-1")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.models.length()").value(0));
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        "INSERT INTO team_model_permissions (team_id, model_id) VALUES (2001, 5001)",
        "INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (2001, 6001)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void bearerHeaderIsAccepted() throws Exception {
        mockHealth();

        mvc.perform(post("/logosdb/get_model_health")
                .header("Authorization", "Bearer dev-key-1")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.models.length()").value(1));
    }

    @Test
    void missingKeyIsRejected() throws Exception {
        mockHealth();

        mvc.perform(post("/logosdb/get_model_health")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized())
           .andExpect(jsonPath("$.detail").value("Invalid or missing API key"));
    }

    @Test
    void unknownKeyIsRejected() throws Exception {
        mockHealth();

        mvc.perform(post("/logosdb/get_model_health")
                .header("logos_key", "not-a-real-key")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized())
           .andExpect(jsonPath("$.detail").value("Invalid or missing API key"));
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        "INSERT INTO team_model_permissions (team_id, model_id) VALUES (2001, 5001)",
        "INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (2001, 6001)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void jwtIsNotAcceptedAsApiKey() throws Exception {
        mockHealth();

        // A Keycloak JWT without a Logos API key must not grant access here.
        mvc.perform(post("/logosdb/get_model_health")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }
}
