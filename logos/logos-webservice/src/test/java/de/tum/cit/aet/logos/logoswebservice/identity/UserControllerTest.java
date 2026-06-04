package de.tum.cit.aet.logos.logoswebservice.identity;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
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
@Sql(scripts = "/sql/seed-identity.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = "/sql/cleanup-identity.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class UserControllerTest {

    @Autowired MockMvc mvc;

    @Test
    void listUsers_requires_admin_key() throws Exception {
        mvc.perform(get("/users").header("logos-key", "dev-key-1"))
           .andExpect(status().isForbidden());
    }

    @Test
    void listUsers_returns_list_for_admin() throws Exception {
        mvc.perform(get("/users").header("logos-key", "admin-key-1"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray());
    }

    @Test
    void listAdmins_returns_only_admins() throws Exception {
        mvc.perform(get("/users/admins").header("logos-key", "admin-key-1"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray());
    }

    @Test
    void patchUserRole_requires_logos_admin() throws Exception {
        mvc.perform(patch("/users/1001/role")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"role\":\"app_admin\"}"))
        .andExpect(status().isForbidden());
    }

    @Test
    void deleteUser_requires_logos_admin() throws Exception {
        mvc.perform(delete("/users/1001")
                .header("logos-key", "admin-key-1"))
        .andExpect(status().isForbidden());
    }

    @Test
    void createUser_returns_created_user() throws Exception {
        mvc.perform(post("/users")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"username\":\"newuser\",\"prename\":\"N\",\"name\":\"User\",\"email\":\"n@n.com\",\"role\":\"app_developer\",\"team_ids\":[]}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.username").value("newuser"));
    }
}