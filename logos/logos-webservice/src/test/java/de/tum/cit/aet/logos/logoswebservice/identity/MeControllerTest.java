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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
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
@Sql(scripts = "/sql/seed-identity.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = "/sql/cleanup-identity.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class MeControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void returns401WithNoToken() throws Exception {
        mvc.perform(get("/me"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void returnsUserDataForValidToken() throws Exception {
        mvc.perform(get("/me").with(TestJwt.testUser()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.username").value("testuser"))
           .andExpect(jsonPath("$.role").value("app_developer"))
           .andExpect(jsonPath("$.user_id").isNumber());
    }

    @Test
    void getRole_logosAdminReturnsRoot() throws Exception {
        mvc.perform(post("/logosdb/get_role")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.role").value("root"));
    }

    @Test
    void getRole_developerReturnsEntity() throws Exception {
        mvc.perform(post("/logosdb/get_role")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.role").value("entity"));
    }

    @Test
    void getApiKeyId_returnsFirstActiveKeyId() throws Exception {
        mvc.perform(post("/logosdb/get_api_key_id")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value(3001));
    }

    @Test
    @Sql(statements = "UPDATE api_keys SET is_active = false WHERE id = 3003",
         executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void getApiKeyId_noActiveKey_returns404() throws Exception {
        mvc.perform(post("/logosdb/get_api_key_id")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isNotFound())
           .andExpect(jsonPath("$.detail").isString());
    }

    @Test
    void setLog_adminCanChangeOtherKey() throws Exception {
        mvc.perform(post("/logosdb/set_log")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"api_key_id\": 3001, \"set_log\": \"FULL\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").isString());
    }

    @Test
    void setLog_developerCannotChangeOtherUsersKey() throws Exception {
        mvc.perform(post("/logosdb/set_log")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"api_key_id\": 3004, \"set_log\": \"BILLING\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void logosKeys_returnsActiveKeysWithTeamContext() throws Exception {
        mvc.perform(get("/me/logos-keys").with(TestJwt.testUser()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0].id").value(3001))
           .andExpect(jsonPath("$[0].key_value").value("dev-key-1"))
           .andExpect(jsonPath("$[0].team_id").value(2001))
           .andExpect(jsonPath("$[0].team_name").value("test-team"));
    }
}
