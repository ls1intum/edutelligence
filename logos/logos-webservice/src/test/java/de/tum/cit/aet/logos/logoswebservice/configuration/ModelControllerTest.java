package de.tum.cit.aet.logos.logoswebservice.configuration;

import com.jayway.jsonpath.JsonPath;
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
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelCapabilitiesRepository;

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
class ModelControllerTest {

    @Autowired MockMvc mvc;
    @Autowired ModelCapabilitiesRepository modelCapabilitiesRepository;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void getModels_logosAdminReturnsAllModels() throws Exception {
        mvc.perform(post("/logosdb/get_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$[0].id").exists())
           .andExpect(jsonPath("$[0].name").exists());
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        "INSERT INTO team_model_permissions (team_id, model_id) VALUES (2001, 5001)",
        "INSERT INTO team_provider_permissions (team_id, provider_id) VALUES (2001, 6001)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void getModels_appAdminReturnsOnlyTeamAssignedModels() throws Exception {
        mvc.perform(post("/logosdb/get_models")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0].id").value(5001))
           .andExpect(jsonPath("$[0].name").value("gpt-4"));
    }

    @Test
    void getModels_requiresAuth() throws Exception {
        mvc.perform(post("/logosdb/get_models")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void addModel_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"name\":\"new-model\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void addModel_logosAdminCanCreate() throws Exception {
        mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"test-model\",\"tags\":\"\",\"description\":\"\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.model_id").isNumber());
    }

    @Test
    void addModel_modelResponseExposesNoParallelField() throws Exception {
        // models.parallel has been dropped from the schema; parallel capacity
        // is derived by the orchestrator from the worker's live lane signals.
        MvcResult addResult = mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"no-parallel-model\"}"))
           .andExpect(status().isOk())
           .andReturn();
        int modelId = JsonPath.read(addResult.getResponse().getContentAsString(), "$.model_id");

        mvc.perform(post("/logosdb/get_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":" + modelId + "}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.id").value(modelId))
           .andExpect(jsonPath("$.parallel").doesNotExist());

        mvc.perform(post("/logosdb/get_models")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[?(@.id == %d)].parallel".formatted(modelId)).doesNotExist());
    }

    @Test
    void updateModelInfo_updatesNameField() throws Exception {
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"name\":\"updated-name\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Model updated"));
    }

    @Test
    void deleteModel_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/delete_model")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void deleteModel_logosAdminCanDelete() throws Exception {
        mvc.perform(post("/logosdb/delete_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Deleted Model"));
    }

    @Test
    void getModel_returnsCorrectFields() throws Exception {
        mvc.perform(post("/logosdb/get_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.id").value(5001))
           .andExpect(jsonPath("$.name").value("gpt-4"));
    }

    @Test
    void getGeneralModelStats_returnsCount() throws Exception {
        mvc.perform(post("/logosdb/get_general_model_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.totalModels").isNumber());
    }

    @Test
    void updateModel_logosAdminCanGiveFeedback() throws Exception {
        mvc.perform(post("/logosdb/update_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001,\"category\":\"accuracy\",\"value\":2}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Updated Model"));
    }

    @Test
    void updateModel_invalidCategoryReturns400() throws Exception {
        mvc.perform(post("/logosdb/update_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001,\"category\":\"bogus\",\"value\":1}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void updateModel_nonAdminIsForbidden() throws Exception {
        mvc.perform(post("/logosdb/update_model")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"id\":5001,\"category\":\"accuracy\",\"value\":1}"))
           .andExpect(status().isForbidden());
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        // Values the local catalog derives for gpt-4 (function calling via the plain
        // "gpt-4" entry, no vision/reasoning entries)
        "INSERT INTO model_capabilities (model_id, supports_function_calling, supports_vision, supports_reasoning) "
            + "VALUES (5001, true, false, false)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void getModelCapabilities_existingModelReturnsCapabilities() throws Exception {
        mvc.perform(post("/logosdb/get_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"ids\":[5001]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.5001.model_id").value(5001))
           .andExpect(jsonPath("$.5001.supports_function_calling").value(true))
           .andExpect(jsonPath("$.5001.supports_vision").value(false))
           .andExpect(jsonPath("$.5001.supports_reasoning").value(false));
    }

    @Test
    void getModelCapabilities_unknownModelReturns404() throws Exception {
        mvc.perform(post("/logosdb/get_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"ids\":[9999]}"))
           .andExpect(status().isNotFound())
           .andExpect(jsonPath("$.error").value("Model not found: 9999"));
    }

    @Test
    void getModelCapabilities_mixedKnownAndUnknownIdsReturns404() throws Exception {
        mvc.perform(post("/logosdb/get_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"ids\":[5001,9999]}"))
           .andExpect(status().isNotFound())
           .andExpect(jsonPath("$.error").value("Model not found: 9999"));
    }

    @Test
    void getModelCapabilities_existingModelWithoutCapabilitiesRowReturnsEmptyMap() throws Exception {
        // gpt-3.5 (5002) exists but has no model_capabilities row
        mvc.perform(post("/logosdb/get_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"ids\":[5002]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isEmpty());
    }

    @Test
    void getModelCapabilities_missingIdsReturns400() throws Exception {
        mvc.perform(post("/logosdb/get_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").value("ids are required"));
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        "INSERT INTO model_capabilities (model_id, supports_function_calling, supports_vision, supports_reasoning) "
            + "VALUES (5001, true, false, false)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void deleteModel_cascadesToModelCapabilities() throws Exception {
        assertThat(modelCapabilitiesRepository.findByModelId(5001)).isPresent();

        mvc.perform(post("/logosdb/delete_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Deleted Model"));

        assertThat(modelCapabilitiesRepository.findByModelId(5001)).isEmpty();
    }
}
