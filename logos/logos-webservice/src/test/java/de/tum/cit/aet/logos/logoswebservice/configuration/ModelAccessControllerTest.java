package de.tum.cit.aet.logos.logoswebservice.configuration;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;

/**
 * Seed layout: model 5001 'gpt-4' is hosted by provider 6001
 * 'openai-provider' (model_provider 7001); model 5002 'gpt-3.5' has no
 * hosting provider. Teams 2001 'test-team' and 2002 'kc-team' exist; keys
 * 3001-3004 belong to team 2001 with use_custom_permissions = false.
 */
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
class ModelAccessControllerTest {

    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;
    @MockitoBean JwtDecoder jwtDecoder;

    private void grantTeamModel(int teamId, String modelIds) throws Exception {
        mvc.perform(put("/admin/teams/" + teamId + "/model-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_ids\":" + modelIds + "}"))
           .andExpect(status().isOk());
    }

    private void grantTeamProvider(int teamId, String providerIds) throws Exception {
        mvc.perform(put("/admin/teams/" + teamId + "/provider-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_ids\":" + providerIds + "}"))
           .andExpect(status().isOk());
    }

    @Test
    void getModelAccess_requiresLogosAdmin() throws Exception {
        mvc.perform(get("/admin/models/5001/access").with(TestJwt.adminUser()))
           .andExpect(status().isForbidden());

        mvc.perform(get("/admin/models/5001/access").with(TestJwt.testUser()))
           .andExpect(status().isForbidden());
    }

    @Test
    void getModelAccess_unknownModelReturns404() throws Exception {
        mvc.perform(get("/admin/models/9999/access").with(TestJwt.logosAdmin()))
           .andExpect(status().isNotFound());
    }

    @Test
    void getModelAccess_returnsProvidersAndEffectiveTeamAccess() throws Exception {
        grantTeamModel(2001, "[5001]");
        grantTeamProvider(2001, "[6001]");

        mvc.perform(get("/admin/models/5001/access").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           // Model facts
           .andExpect(jsonPath("$.model.id").value(5001))
           .andExpect(jsonPath("$.model.name").value("gpt-4"))
           // Exactly the one hosting provider, with usage figures
           .andExpect(jsonPath("$.providers.length()").value(1))
           .andExpect(jsonPath("$.providers[0].provider_id").value(6001))
           .andExpect(jsonPath("$.providers[0].name").value("openai-provider"))
           .andExpect(jsonPath("$.providers[0].request_count").value(0))
           .andExpect(jsonPath("$.providers[0].last_request_at").doesNotExist())
           // Team 2001: model + provider grant -> effective; team 2002: nothing
           .andExpect(jsonPath("$.teams.length()").value(2))
           .andExpect(jsonPath("$.teams[0].team_id").value(2001))
           .andExpect(jsonPath("$.teams[0].team_name").value("test-team"))
           .andExpect(jsonPath("$.teams[0].model_grant").value(true))
           .andExpect(jsonPath("$.teams[0].provider_grants.length()").value(1))
           .andExpect(jsonPath("$.teams[0].provider_grants[0].provider_id").value(6001))
           .andExpect(jsonPath("$.teams[0].provider_grants[0].granted").value(true))
           .andExpect(jsonPath("$.teams[0].effective_access").value(true))
           .andExpect(jsonPath("$.teams[1].team_id").value(2002))
           .andExpect(jsonPath("$.teams[1].model_grant").value(false))
           .andExpect(jsonPath("$.teams[1].provider_grants[0].granted").value(false))
           .andExpect(jsonPath("$.teams[1].effective_access").value(false))
           // No custom-permission keys in the seed
           .andExpect(jsonPath("$.api_keys.length()").value(0));
    }

    @Test
    void getModelAccess_flagsOrphanedModelGrant() throws Exception {
        // Model grant without any provider grant: the model can never route.
        grantTeamModel(2001, "[5001]");

        mvc.perform(get("/admin/models/5001/access").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.teams[0].model_grant").value(true))
           .andExpect(jsonPath("$.teams[0].provider_grants[0].granted").value(false))
           .andExpect(jsonPath("$.teams[0].effective_access").value(false));
    }

    @Test
    void getModelAccess_modelWithoutHostProviderHasNoProviderColumns() throws Exception {
        grantTeamModel(2001, "[5002]");

        mvc.perform(get("/admin/models/5002/access").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.providers.length()").value(0))
           // The grant still shows up (and is orphaned), with empty columns.
           .andExpect(jsonPath("$.teams[0].team_id").value(2001))
           .andExpect(jsonPath("$.teams[0].model_grant").value(true))
           .andExpect(jsonPath("$.teams[0].provider_grants.length()").value(0))
           .andExpect(jsonPath("$.teams[0].effective_access").value(false));
    }

    @Test
    void getModelAccess_listsCustomPermissionKeyWithEffectiveAccess() throws Exception {
        jdbc.update("UPDATE api_keys SET use_custom_permissions = true WHERE id = 3001");
        mvc.perform(put("/admin/api-keys/3001/model-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_ids\":[5001]}"))
           .andExpect(status().isOk());
        mvc.perform(put("/admin/api-keys/3001/provider-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_ids\":[6001]}"))
           .andExpect(status().isOk());

        mvc.perform(get("/admin/models/5001/access").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           // Only the custom-permission key shows up; 3002-3004 inherit team grants.
           .andExpect(jsonPath("$.api_keys.length()").value(1))
           .andExpect(jsonPath("$.api_keys[0].key_id").value(3001))
           .andExpect(jsonPath("$.api_keys[0].key_name").value("dev key"))
           .andExpect(jsonPath("$.api_keys[0].is_active").value(true))
           .andExpect(jsonPath("$.api_keys[0].team_id").value(2001))
           .andExpect(jsonPath("$.api_keys[0].team_name").value("test-team"))
           .andExpect(jsonPath("$.api_keys[0].model_grant").value(true))
           .andExpect(jsonPath("$.api_keys[0].provider_grants[0].provider_id").value(6001))
           .andExpect(jsonPath("$.api_keys[0].provider_grants[0].granted").value(true))
           .andExpect(jsonPath("$.api_keys[0].effective_access").value(true));
    }

    @Test
    void getModelAccess_flagsOrphanedKeyGrant() throws Exception {
        jdbc.update("UPDATE api_keys SET use_custom_permissions = true WHERE id = 3001");
        mvc.perform(put("/admin/api-keys/3001/model-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model_ids\":[5001]}"))
           .andExpect(status().isOk());

        mvc.perform(get("/admin/models/5001/access").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.api_keys.length()").value(1))
           .andExpect(jsonPath("$.api_keys[0].model_grant").value(true))
           .andExpect(jsonPath("$.api_keys[0].provider_grants[0].granted").value(false))
           .andExpect(jsonPath("$.api_keys[0].effective_access").value(false));
    }

    @Test
    void getModelAccess_keyWithOnlyHostProviderGrantIsListed() throws Exception {
        jdbc.update("UPDATE api_keys SET use_custom_permissions = true WHERE id = 3001");
        mvc.perform(put("/admin/api-keys/3001/provider-permissions")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"provider_ids\":[6001]}"))
           .andExpect(status().isOk());

        mvc.perform(get("/admin/models/5001/access").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.api_keys.length()").value(1))
           .andExpect(jsonPath("$.api_keys[0].model_grant").value(false))
           .andExpect(jsonPath("$.api_keys[0].provider_grants[0].granted").value(true))
           .andExpect(jsonPath("$.api_keys[0].effective_access").value(false));
    }
}
