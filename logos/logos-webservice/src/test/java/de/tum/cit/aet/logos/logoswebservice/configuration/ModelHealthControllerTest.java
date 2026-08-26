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

    private static Map<String, Object> entry(int modelId, String name, String status,
            List<Map<String, Object>> deployments) {
        Map<String, Object> model = new LinkedHashMap<>();
        model.put("model_id", modelId);
        model.put("name", name);
        model.put("status", status);
        model.put("deployments", deployments);
        return model;
    }

    private static Map<String, Object> deployment(int providerId, String providerName, String type,
            String status, String state) {
        Map<String, Object> deployment = new LinkedHashMap<>();
        deployment.put("provider_id", providerId);
        deployment.put("provider_name", providerName);
        deployment.put("type", type);
        deployment.put("status", status);
        if (state != null) deployment.put("state", state);
        return deployment;
    }

    @Test
    void getModelHealth_logosAdminSeesAllModels() throws Exception {
        when(modelHealthClient.getModelHealth()).thenReturn(List.of(
            entry(5001, "gpt-4", "UP", List.of(
                deployment(6001, "openai-provider", "cloud", "UP", null))),
            entry(5002, "gpt-3.5", "DOWN", List.of())
        ));

        mvc.perform(post("/logosdb/get_model_health")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.models.length()").value(2))
           .andExpect(jsonPath("$.models[0].model_id").value(5001))
           .andExpect(jsonPath("$.models[0].name").value("gpt-4"))
           .andExpect(jsonPath("$.models[0].status").value("UP"))
           .andExpect(jsonPath("$.models[0].deployments[0].provider_id").value(6001))
           .andExpect(jsonPath("$.models[0].deployments[0].status").value("UP"))
           .andExpect(jsonPath("$.models[1].status").value("DOWN"));
    }

    @Test
    void getModelHealth_reportsWorkerDeploymentState() throws Exception {
        when(modelHealthClient.getModelHealth()).thenReturn(List.of(
            entry(5001, "gpt-4", "UP", List.of(
                deployment(7001, "gpu-node-1", "logosnode", "UP", "warm"),
                deployment(7002, "gpu-node-2", "logosnode", "DOWN", "offline")))
        ));

        mvc.perform(post("/logosdb/get_model_health")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.models[0].deployments[0].state").value("warm"))
           .andExpect(jsonPath("$.models[0].deployments[1].state").value("offline"));
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        "INSERT INTO team_model_permissions (team_id, model_id) VALUES (2001, 5001)",
        "INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (2001, 6001)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void getModelHealth_regularUserSeesOnlyTeamAssignedModels() throws Exception {
        when(modelHealthClient.getModelHealth()).thenReturn(List.of(
            entry(5001, "gpt-4", "UP", List.of(
                deployment(6001, "openai-provider", "cloud", "UP", null))),
            entry(5002, "gpt-3.5", "UP", List.of())
        ));

        mvc.perform(post("/logosdb/get_model_health")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.models.length()").value(1))
           .andExpect(jsonPath("$.models[0].model_id").value(5001));
    }

    @Test
    void getModelHealth_requiresAuth() throws Exception {
        mvc.perform(post("/logosdb/get_model_health")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }
}
