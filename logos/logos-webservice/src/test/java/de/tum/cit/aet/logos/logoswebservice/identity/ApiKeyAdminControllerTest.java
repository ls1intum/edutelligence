package de.tum.cit.aet.logos.logoswebservice.identity;

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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
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
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-admin.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-admin.sql", "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class ApiKeyAdminControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void getTeamApiKeys_requiresAppAdminOrAbove() throws Exception {
        mvc.perform(get("/admin/teams/2001/api-keys")
                .with(TestJwt.testUser()))
           .andExpect(status().isForbidden());
    }

    @Test
    void getTeamApiKeys_logosAdminReturnsKeys() throws Exception {
        mvc.perform(get("/admin/teams/2001/api-keys")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray());
    }

    @Test
    void createAppKey_requiresAppAdminOrAbove() throws Exception {
        mvc.perform(post("/admin/teams/2001/api-keys")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"name\":\"test-key\",\"key_type\":\"application\",\"environment\":\"test\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void createAppKey_logosAdminCreatesKey() throws Exception {
        mvc.perform(post("/admin/teams/2001/api-keys")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"new-app-key\",\"key_type\":\"application\",\"environment\":\"staging\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Application Key created"))
           .andExpect(jsonPath("$.id").isNumber())
           .andExpect(jsonPath("$.api_key").isString());
    }

    @Test
    void createAppKey_rejectsDuplicateEnvironment() throws Exception {
        mvc.perform(post("/admin/teams/2001/api-keys")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"key-a\",\"key_type\":\"application\",\"environment\":\"prod\"}"))
           .andExpect(status().isOk());
        mvc.perform(post("/admin/teams/2001/api-keys")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"key-b\",\"key_type\":\"application\",\"environment\":\"prod\"}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void deactivateKey_requiresAppAdminOrAbove() throws Exception {
        mvc.perform(delete("/admin/api-keys/3001")
                .with(TestJwt.testUser()))
           .andExpect(status().isForbidden());
    }

    @Test
    void deactivateKey_logosAdminDeactivates() throws Exception {
        mvc.perform(delete("/admin/api-keys/3001")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("API Key deleted successfully"));
    }

    @Test
    void patchKey_logosAdminUpdatesKey() throws Exception {
        mvc.perform(patch("/admin/api-keys/3001")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"default_priority\":3}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("API Key updated successfully"));
    }

    @Test
    void patchKey_returnsNotFoundForMissingKey() throws Exception {
        mvc.perform(patch("/admin/api-keys/99999")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"default_priority\":3}"))
           .andExpect(status().isNotFound());
    }
}
