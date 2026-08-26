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
import org.springframework.test.context.jdbc.SqlMergeMode;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.fail;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelCapabilities;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelCapabilitiesRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelCapabilitiesUpdaterService;

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
    @Autowired ModelCapabilitiesUpdaterService modelCapabilitiesUpdaterService;
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
                .content("{\"name\":\"test-model\",\"parallel\":1,\"tags\":\"\",\"description\":\"\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.model_id").isNumber());
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        "INSERT INTO model_capabilities (model_id, supports_function_calling, supports_vision, supports_reasoning) "
            + "VALUES (5001, true, false, false)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void updateModelInfo_updatesNameField() throws Exception {
        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"name\":\"updated-name\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Model updated"));

        // The rename triggers the async capability sync. 'updated-name' is not in the
        // local catalog, so the seeded row gets deleted; await completion so the
        // in-flight task cannot delete rows seeded by later tests.
        awaitCapabilitiesRow(5001, false);
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        "INSERT INTO model_capabilities (model_id, supports_function_calling, supports_vision, supports_reasoning) "
            + "VALUES (5001, true, false, false)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void updateModelInfo_renameToUnknownNameDeletesCapabilitiesRow() throws Exception {
        // A lingering async capability sync from a previous rename test may already have
        // deleted the seeded row; (re-)insert until the row sticks.
        long deadline = System.currentTimeMillis() + 10_000;
        while (modelCapabilitiesRepository.findByModelId(5001).isEmpty()) {
            if (System.currentTimeMillis() > deadline) {
                fail("could not (re-)insert the capability row for model 5001");
            }
            modelCapabilitiesRepository.save(new ModelCapabilities(5001, true, false, false));
            Thread.sleep(50);
        }
        assertThat(modelCapabilitiesRepository.findByModelId(5001)).isPresent();

        mvc.perform(post("/logosdb/update_model_info")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"name\":\"renamed-unknown-model\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Model updated"));

        // 'renamed-unknown-model' is not in the local catalog, so the async capability
        // sync must delete the row; await completion so the in-flight task cannot
        // interfere with later tests.
        awaitCapabilitiesRow(5001, false);
    }

    private void awaitCapabilitiesRow(int modelId, boolean expectedPresent) throws InterruptedException {
        long deadline = System.currentTimeMillis() + 10_000;
        while (modelCapabilitiesRepository.findByModelId(modelId).isPresent() != expectedPresent) {
            if (System.currentTimeMillis() > deadline) {
                fail("capability row for model " + modelId + " did not reach the expected state within the deadline");
            }
            Thread.sleep(50);
        }
        assertThat(modelCapabilitiesRepository.findByModelId(modelId).isPresent()).isEqualTo(expectedPresent);
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
           .andExpect(jsonPath("$.5001.supports_reasoning").value(false))
           .andExpect(jsonPath("$.5001.manual_override").value(false));
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

    @Test
    void setModelCapabilities_createsRowAndMarksManual() throws Exception {
        // gpt-3.5 (5002) exists but has no model_capabilities row yet
        mvc.perform(post("/logosdb/set_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5002,\"supports_function_calling\":true,"
                    + "\"supports_vision\":true,\"supports_reasoning\":false}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.model_id").value(5002))
           .andExpect(jsonPath("$.supports_function_calling").value(true))
           .andExpect(jsonPath("$.supports_vision").value(true))
           .andExpect(jsonPath("$.supports_reasoning").value(false))
           .andExpect(jsonPath("$.manual_override").value(true));

        mvc.perform(post("/logosdb/get_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"ids\":[5002]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.5002.supports_function_calling").value(true))
           .andExpect(jsonPath("$.5002.supports_vision").value(true))
           .andExpect(jsonPath("$.5002.supports_reasoning").value(false))
           .andExpect(jsonPath("$.5002.manual_override").value(true));
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(statements = {
        "INSERT INTO model_capabilities (model_id, supports_function_calling, supports_vision, supports_reasoning) "
            + "VALUES (5001, true, false, false)"
    }, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void setModelCapabilities_overwritesExistingRow() throws Exception {
        mvc.perform(post("/logosdb/set_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"supports_function_calling\":false,"
                    + "\"supports_vision\":true,\"supports_reasoning\":true}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.model_id").value(5001))
           .andExpect(jsonPath("$.supports_function_calling").value(false))
           .andExpect(jsonPath("$.supports_vision").value(true))
           .andExpect(jsonPath("$.supports_reasoning").value(true))
           .andExpect(jsonPath("$.manual_override").value(true));

        mvc.perform(post("/logosdb/get_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"ids\":[5001]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.5001.supports_function_calling").value(false))
           .andExpect(jsonPath("$.5001.supports_vision").value(true))
           .andExpect(jsonPath("$.5001.supports_reasoning").value(true))
           .andExpect(jsonPath("$.5001.manual_override").value(true));
    }

    @Test
    void setModelCapabilities_unknownModelReturns404() throws Exception {
        mvc.perform(post("/logosdb/set_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":9999,\"supports_function_calling\":true,"
                    + "\"supports_vision\":false,\"supports_reasoning\":false}"))
           .andExpect(status().isNotFound())
           .andExpect(jsonPath("$.error").value("Model not found: 9999"));
    }

    @Test
    void setModelCapabilities_missingFieldsReturn400() throws Exception {
        mvc.perform(post("/logosdb/set_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"supports_function_calling\":true}"))
           .andExpect(status().isBadRequest());

        mvc.perform(post("/logosdb/set_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"supports_function_calling\":true,\"supports_vision\":true,\"supports_reasoning\":false}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void resetModelCapabilities_clearsOverrideAndResyncsFromCatalog() throws Exception {
        // Set a manual override that differs from the catalog (gpt-4 has
        // supports_function_calling=true and no vision/reasoning entries)
        mvc.perform(post("/logosdb/set_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"supports_function_calling\":false,"
                    + "\"supports_vision\":true,\"supports_reasoning\":true}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.manual_override").value(true))
           .andExpect(jsonPath("$.supports_vision").value(true));

        mvc.perform(post("/logosdb/reset_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.model_id").value(5001))
           .andExpect(jsonPath("$.supports_function_calling").value(true))
           .andExpect(jsonPath("$.supports_vision").value(false))
           .andExpect(jsonPath("$.supports_reasoning").value(false))
           .andExpect(jsonPath("$.manual_override").value(false));

        mvc.perform(post("/logosdb/get_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"ids\":[5001]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.5001.supports_function_calling").value(true))
           .andExpect(jsonPath("$.5001.supports_vision").value(false))
           .andExpect(jsonPath("$.5001.supports_reasoning").value(false))
           .andExpect(jsonPath("$.5001.manual_override").value(false));
    }

    @Test
    void resetModelCapabilities_unknownModelReturns404() throws Exception {
        mvc.perform(post("/logosdb/reset_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":9999}"))
           .andExpect(status().isNotFound())
           .andExpect(jsonPath("$.error").value("Model not found: 9999"));
    }

    @Test
    void scheduledRefresh_keepsManualOverride() throws Exception {
        // Core persistence requirement: once an admin overrides the capabilities,
        // the catalog refresh must not touch the row (neither overwrite on match
        // nor delete on no-match)
        mvc.perform(post("/logosdb/set_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_id\":5001,\"supports_function_calling\":false,"
                    + "\"supports_vision\":true,\"supports_reasoning\":true}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.manual_override").value(true));

        // The scheduled daily refresh, invoked directly so it runs synchronously
        modelCapabilitiesUpdaterService.updateAllModelCapabilities();

        mvc.perform(post("/logosdb/get_model_capabilities")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"ids\":[5001]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.5001.supports_function_calling").value(false))
           .andExpect(jsonPath("$.5001.supports_vision").value(true))
           .andExpect(jsonPath("$.5001.supports_reasoning").value(true))
           .andExpect(jsonPath("$.5001.manual_override").value(true));
    }
}
