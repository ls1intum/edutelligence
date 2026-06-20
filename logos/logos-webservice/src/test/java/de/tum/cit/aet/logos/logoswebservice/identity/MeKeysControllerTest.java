package de.tum.cit.aet.logos.logoswebservice.identity;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
        "spring.liquibase.enabled=true",
        "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml"
})
@Sql(scripts = "/sql/seed-me-keys.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = "/sql/cleanup-me-keys.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class MeKeysControllerTest {

    @Autowired MockMvc mvc;

    // GET /me/keys

    @Test
    void getMyKeys_returns401WithNoKey() throws Exception {
        mvc.perform(get("/me/keys"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void getMyKeys_returns403ForServiceKey() throws Exception {
        mvc.perform(get("/me/keys").header("logos-key", "svc-key-1"))
           .andExpect(status().isForbidden());
    }

    @Test
    void getMyKeys_returnsOnlyOwnKeys() throws Exception {
        mvc.perform(get("/me/keys").header("logos-key", "alice-key-1"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0].name").value("alice-alpha-key"))
           .andExpect(jsonPath("$[0].team.name").value("team-alpha"))
           .andExpect(jsonPath("$[0].settings.cloud_rpm_limit").value(60))
           .andExpect(jsonPath("$[0].used_micro_cents").value(0));
    }

    @Test
    void getMyKeys_includesTeamBudget() throws Exception {
        mvc.perform(get("/me/keys").header("logos-key", "alice-key-1"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0].team.team_monthly_budget_micro_cents").value(1000000))
           .andExpect(jsonPath("$[0].team.budget_used_micro_cents").value(0));
    }

    // PATCH /me/keys/{keyId}/log

    @Test
    void setLog_returns400ForInvalidLevel() throws Exception {
        mvc.perform(patch("/me/keys/3101/log")
                .header("logos-key", "alice-key-1")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"log\": \"INVALID\"}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void setLog_returns403WhenNotOwner() throws Exception {
        mvc.perform(patch("/me/keys/3102/log")
                .header("logos-key", "alice-key-1")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"log\": \"FULL\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void setLog_returns404ForUnknownKey() throws Exception {
        mvc.perform(patch("/me/keys/99999/log")
                .header("logos-key", "alice-key-1")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"log\": \"FULL\"}"))
           .andExpect(status().isNotFound());
    }

    @Test
    void setLog_updatesOwnKeySuccessfully() throws Exception {
        mvc.perform(patch("/me/keys/3101/log")
                .header("logos-key", "alice-key-1")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"log\": \"FULL\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").isString());
    }

    // GET /me/keys/{keyId}/models

    @Test
    void getModels_returns403WhenNotOwner() throws Exception {
        mvc.perform(get("/me/keys/3102/models").header("logos-key", "alice-key-1"))
           .andExpect(status().isForbidden());
    }

    @Test
    void getModels_returnsTeamModelList() throws Exception {
        mvc.perform(get("/me/keys/3101/models").header("logos-key", "alice-key-1"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0].model_name").value("test-model"))
           .andExpect(jsonPath("$[0].provider_name").value("test-provider"));
    }

    @Test
    void getModels_returns404ForUnknownKey() throws Exception {
        mvc.perform(get("/me/keys/99999/models").header("logos-key", "alice-key-1"))
           .andExpect(status().isNotFound());
    }
}
