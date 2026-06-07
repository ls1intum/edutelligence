package de.tum.cit.aet.logos.logoswebservice.configuration;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
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
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-admin.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-admin.sql", "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class PermissionControllerTest {

    @Autowired MockMvc mvc;

    @Test
    void getApiKeyModelPermissions_emptyByDefault() throws Exception {
        mvc.perform(get("/admin/api-keys/3001/model-permissions")
                .header("logos-key", "logos-admin-key"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void setAndGetApiKeyModelPermissions() throws Exception {
        mvc.perform(put("/admin/api-keys/3001/model-permissions")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"model_ids\":[5001]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("API Key model permissions updated"));

        mvc.perform(get("/admin/api-keys/3001/model-permissions")
                .header("logos-key", "logos-admin-key"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0]").value(5001));
    }

    @Test
    void setApiKeyModelPermissions_requiresAppAdminOrAbove() throws Exception {
        mvc.perform(put("/admin/api-keys/3001/model-permissions")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{\"model_ids\":[5001]}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void getApiKeyProviderPermissions_emptyByDefault() throws Exception {
        mvc.perform(get("/admin/api-keys/3001/provider-permissions")
                .header("logos-key", "logos-admin-key"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void setApiKeyProviderPermissions_prunesModels() throws Exception {
        mvc.perform(put("/admin/api-keys/3001/model-permissions")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"model_ids\":[5001]}"))
           .andExpect(status().isOk());

        mvc.perform(put("/admin/api-keys/3001/provider-permissions")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"provider_ids\":[]}"))
           .andExpect(status().isOk());

        mvc.perform(get("/admin/api-keys/3001/model-permissions")
                .header("logos-key", "logos-admin-key"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void getTeamModelPermissions_emptyByDefault() throws Exception {
        mvc.perform(get("/admin/teams/2001/model-permissions")
                .header("logos-key", "logos-admin-key"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void setTeamModelPermissions_logosAdminCanSet() throws Exception {
        mvc.perform(put("/admin/teams/2001/model-permissions")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"model_ids\":[5001,5002]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Team model permissions updated"));

        mvc.perform(get("/admin/teams/2001/model-permissions")
                .header("logos-key", "logos-admin-key"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(2));
    }

    @Test
    void setTeamProviderPermissions_requiresLogosAdmin() throws Exception {
        mvc.perform(put("/admin/teams/2001/provider-permissions")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"provider_ids\":[6001]}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void setTeamProviderPermissions_logosAdminCanSet() throws Exception {
        mvc.perform(put("/admin/teams/2001/provider-permissions")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"provider_ids\":[6001]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Team provider permissions updated"));
    }

    @Test
    void getTeamProviderPermissions_emptyByDefault() throws Exception {
        mvc.perform(get("/admin/teams/2001/provider-permissions")
                .header("logos-key", "logos-admin-key"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(0));
    }
}
