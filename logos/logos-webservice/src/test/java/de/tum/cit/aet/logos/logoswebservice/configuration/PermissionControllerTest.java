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
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
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
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-admin.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-admin.sql", "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class PermissionControllerTest {

    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void getApiKeyModelPermissions_emptyByDefault() throws Exception {
        mvc.perform(get("/admin/api-keys/3001/model-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void setAndGetApiKeyModelPermissions() throws Exception {
        mvc.perform(put("/admin/api-keys/3001/model-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_ids\":[5001]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("API Key model permissions updated"));

        mvc.perform(get("/admin/api-keys/3001/model-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0]").value(5001));
    }

    @Test
    void setApiKeyModelPermissions_requiresAppAdminOrAbove() throws Exception {
        mvc.perform(put("/admin/api-keys/3001/model-permissions")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"model_ids\":[5001]}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void getApiKeyProviderPermissions_emptyByDefault() throws Exception {
        mvc.perform(get("/admin/api-keys/3001/provider-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void setApiKeyProviderPermissions_prunesModels() throws Exception {
        mvc.perform(put("/admin/api-keys/3001/model-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_ids\":[5001]}"))
           .andExpect(status().isOk());

        mvc.perform(put("/admin/api-keys/3001/provider-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_ids\":[]}"))
           .andExpect(status().isOk());

        mvc.perform(get("/admin/api-keys/3001/model-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void appAdminTeamOwnerCanOverrideApiKeyPermissions() throws Exception {
        mvc.perform(put("/admin/api-keys/3001/provider-permissions")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"provider_ids\":[6001]}"))
           .andExpect(status().isOk());

        mvc.perform(put("/admin/api-keys/3001/model-permissions")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"model_ids\":[5001]}"))
           .andExpect(status().isOk());

        mvc.perform(get("/admin/api-keys/3001/provider-permissions")
                .with(TestJwt.adminUser()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0]").value(6001));

        mvc.perform(get("/admin/api-keys/3001/model-permissions")
                .with(TestJwt.adminUser()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0]").value(5001));
    }

    @Test
    void appAdminCannotOverrideKeyOutsideOwnedTeam() throws Exception {
        mvc.perform(put("/admin/api-keys/3001/model-permissions")
                .with(TestJwt.forSeededUser(1006, "kcmember", "chair-member"))
                .contentType("application/json")
                .content("{\"model_ids\":[5001]}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void getTeamModelPermissions_emptyByDefault() throws Exception {
        mvc.perform(get("/admin/teams/2001/model-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void setTeamModelPermissions_logosAdminCanSet() throws Exception {
        mvc.perform(put("/admin/teams/2001/model-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_ids\":[5001,5002]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Team model permissions updated"));

        mvc.perform(get("/admin/teams/2001/model-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(2));
    }

    @Test
    void setTeamProviderPermissions_requiresLogosAdmin() throws Exception {
        mvc.perform(put("/admin/teams/2001/provider-permissions")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"provider_ids\":[6001]}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void setTeamProviderPermissions_logosAdminCanSet() throws Exception {
        mvc.perform(put("/admin/teams/2001/provider-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_ids\":[6001]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Team provider permissions updated"));
    }

    @Test
    void getTeamProviderPermissions_emptyByDefault() throws Exception {
        mvc.perform(get("/admin/teams/2001/provider-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void addTeamProviderPermission_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/admin/teams/2001/provider-permissions/6001")
                .with(TestJwt.adminUser()))
           .andExpect(status().isForbidden());
    }

    @Test
    void addTeamProviderPermission_addsOnlyThisGrant() throws Exception {
        // A second provider so "the other grants are kept" is observable.
        jdbc.update("INSERT INTO providers (id, name, base_url, provider_type, privacy_level, auth_name, auth_format) "
            + "VALUES (6002, 'second-provider', 'https://api.second.example', 'cloud', 'LOCAL', 'Authorization', 'Bearer {}')");

        mvc.perform(put("/admin/teams/2001/model-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_ids\":[5001]}"))
           .andExpect(status().isOk());

        mvc.perform(post("/admin/teams/2001/provider-permissions/6001")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Team provider permission added"));
        mvc.perform(post("/admin/teams/2001/provider-permissions/6002")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk());

        // Each add appends one grant without replacing the team's other grants...
        mvc.perform(get("/admin/teams/2001/provider-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(2))
           .andExpect(jsonPath("$[0]").value(6001))
           .andExpect(jsonPath("$[1]").value(6002));

        // ...re-adding the same grant is idempotent (no duplicate rows)...
        mvc.perform(post("/admin/teams/2001/provider-permissions/6001")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk());
        mvc.perform(get("/admin/teams/2001/provider-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(2));

        // ...and the add path never re-runs the model-grant cascade.
        mvc.perform(get("/admin/teams/2001/model-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0]").value(5001));
    }

    @Test
    void removeTeamProviderPermission_requiresLogosAdmin() throws Exception {
        mvc.perform(delete("/admin/teams/2001/provider-permissions/6001")
                .with(TestJwt.adminUser()))
           .andExpect(status().isForbidden());
    }

    @Test
    void removeTeamProviderPermission_removesOnlyThisGrant() throws Exception {
        // A second provider so "the other grants are kept" is observable.
        jdbc.update("INSERT INTO providers (id, name, base_url, provider_type, privacy_level, auth_name, auth_format) "
            + "VALUES (6002, 'second-provider', 'https://api.second.example', 'cloud', 'LOCAL', 'Authorization', 'Bearer {}')");

        mvc.perform(put("/admin/teams/2001/model-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_ids\":[5001]}"))
           .andExpect(status().isOk());
        mvc.perform(post("/admin/teams/2001/provider-permissions/6001")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk());
        mvc.perform(post("/admin/teams/2001/provider-permissions/6002")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk());

        // Removes exactly the requested grant, keeping the team's other grants...
        mvc.perform(delete("/admin/teams/2001/provider-permissions/6001")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Team provider permission removed"));
        mvc.perform(get("/admin/teams/2001/provider-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0]").value(6002));

        // ...removing a missing grant is an idempotent no-op...
        mvc.perform(delete("/admin/teams/2001/provider-permissions/6001")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk());
        mvc.perform(get("/admin/teams/2001/provider-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1));

        // ...and the remove path never re-runs the model-grant cascade.
        mvc.perform(get("/admin/teams/2001/model-permissions")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0]").value(5001));
    }
}
