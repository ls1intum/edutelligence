package de.tum.cit.aet.logos.logoswebservice.configuration;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class ModelControllerTest {

    @Autowired MockMvc mvc;

    @Test
    void getModels_adminReturnsAllModels() throws Exception {
        mvc.perform(post("/logosdb/get_models")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"logos_key\":\"logos-admin-key\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$[0].id").exists())
           .andExpect(jsonPath("$[0].name").exists());
    }

    @Test
    void getModels_requiresValidKey() throws Exception {
        mvc.perform(post("/logosdb/get_models")
                .header("logos-key", "invalid-key")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void addModel_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/add_model")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"name\":\"new-model\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void addModel_logosAdminCanCreate() throws Exception {
        mvc.perform(post("/logosdb/add_model")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"name\":\"test-model\",\"parallel\":1,\"tags\":\"\",\"description\":\"\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.model_id").isNumber());
    }

    @Test
    void updateModelInfo_updatesNameField() throws Exception {
        mvc.perform(post("/logosdb/update_model_info")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"model_id\":5001,\"name\":\"updated-name\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Model updated"));
    }

    @Test
    void deleteModel_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/delete_model")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void deleteModel_logosAdminCanDelete() throws Exception {
        mvc.perform(post("/logosdb/delete_model")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Deleted Model"));
    }

    @Test
    void getModel_returnsCorrectFields() throws Exception {
        mvc.perform(post("/logosdb/get_model")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.id").value(5001))
           .andExpect(jsonPath("$.name").value("gpt-4"));
    }

    @Test
    void getGeneralModelStats_returnsCount() throws Exception {
        mvc.perform(post("/logosdb/get_general_model_stats")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.totalModels").isNumber());
    }

    @Test
    void updateModel_logosAdminCanGiveFeedback() throws Exception {
        mvc.perform(post("/logosdb/update_model")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"id\":5001,\"category\":\"accuracy\",\"value\":2}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Updated Model"));
    }

    @Test
    void updateModel_invalidCategoryReturns400() throws Exception {
        mvc.perform(post("/logosdb/update_model")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"id\":5001,\"category\":\"bogus\",\"value\":1}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void updateModel_nonAdminIsForbidden() throws Exception {
        mvc.perform(post("/logosdb/update_model")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{\"id\":5001,\"category\":\"accuracy\",\"value\":1}"))
           .andExpect(status().isForbidden());
    }
}