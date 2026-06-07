package de.tum.cit.aet.logos.logoswebservice.admin;

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
@Sql(scripts = {"/sql/seed-identity.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class AdminUtilControllerTest {

    @Autowired MockMvc mvc;

    @Test
    void getRole_logosAdminReturnsRoot() throws Exception {
        mvc.perform(post("/logosdb/get_role")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.role").value("root"));
    }

    @Test
    void getRole_developerReturnsEntity() throws Exception {
        mvc.perform(post("/logosdb/get_role")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.role").value("entity"));
    }

    @Test
    void getApiKeyId_returnsKeyId() throws Exception {
        mvc.perform(post("/logosdb/get_api_key_id")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value(3001));
    }

    @Test
    void setLog_adminCanChangeOtherKey() throws Exception {
        mvc.perform(post("/logosdb/set_log")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"api_key_id\": 3001, \"set_log\": \"FULL\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").isString());
    }

    @Test
    void setLog_developerCannotChangeOtherKey() throws Exception {
        mvc.perform(post("/logosdb/set_log")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{\"api_key_id\": 3004, \"set_log\": \"BILLING\"}"))
           .andExpect(status().isForbidden());
    }
}