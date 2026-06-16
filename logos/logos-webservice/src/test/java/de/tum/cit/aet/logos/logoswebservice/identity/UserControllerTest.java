package de.tum.cit.aet.logos.logoswebservice.identity;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
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
        .andExpect(jsonPath("$.username").value("nuser"));
    }

    @Test
    void createUser_appAdminCanAddToOwnedTeam() throws Exception {
        mvc.perform(post("/users")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"username\":\"u2\",\"prename\":\"A\",\"name\":\"B\",\"email\":\"a@b.com\",\"role\":\"app_developer\",\"team_ids\":[2001]}"))
        .andExpect(status().isOk());
    }

    @Test
    void createUser_appAdminCannotAddToNonOwnedTeam() throws Exception {
        mvc.perform(post("/users")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"username\":\"u3\",\"prename\":\"A\",\"name\":\"B\",\"email\":\"c@d.com\",\"role\":\"app_developer\",\"team_ids\":[9999]}"))
        .andExpect(status().isForbidden());
    }

    @Test
    void patchUserInfo_succeeds_for_app_admin() throws Exception {
        mvc.perform(patch("/users/1001")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"prename\":\"Updated\",\"name\":\"Name\",\"email\":\"upd@test.com\"}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.prename").value("Updated"));
    }

    @Test
    void patchUserInfo_forbidden_for_developer() throws Exception {
        mvc.perform(patch("/users/1001")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{\"prename\":\"X\"}"))
        .andExpect(status().isForbidden());
    }

    @Test
    void importUsers_returns_summary() throws Exception {
        String csv = "prename,name,email,team\nAlice,Smith,alice@import.com,test-team\n";
        mvc.perform(multipart("/users/import")
                .file(new MockMultipartFile("file", "users.csv", "text/csv", csv.getBytes()))
                .header("logos-key", "admin-key-1"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.summary.created").value(1));
    }

    @Test
    void importUsers_rejects_non_csv() throws Exception {
        mvc.perform(multipart("/users/import")
                .file(new MockMultipartFile("file", "users.txt", "text/plain", "data".getBytes()))
                .header("logos-key", "admin-key-1"))
        .andExpect(status().isBadRequest());
    }

    @Test
    void importUsers_forbidden_for_developer() throws Exception {
        String csv = "prename,name,email\nAlice,Smith,alice2@import.com\n";
        mvc.perform(multipart("/users/import")
                .file(new MockMultipartFile("file", "users.csv", "text/csv", csv.getBytes()))
                .header("logos-key", "dev-key-1"))
        .andExpect(status().isForbidden());
    }
}
