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
class TeamControllerTest {

    @Autowired MockMvc mvc;

    @Test
    void listTeams_returns_teams_for_admin() throws Exception {
        mvc.perform(get("/teams").header("logos-key", "admin-key-1"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray());
    }

    @Test
    void listTeams_requires_admin() throws Exception {
        mvc.perform(get("/teams").header("logos-key", "dev-key-1"))
           .andExpect(status().isForbidden());
    }

    @Test
    void createTeam_returns_new_team() throws Exception {
        mvc.perform(post("/teams")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"name\":\"new-team\",\"owner_ids\":[]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.name").value("new-team"));
    }

    @Test
    void getTeamMembers_returns_team_detail() throws Exception {
        mvc.perform(get("/teams/2001/members").header("logos-key", "admin-key-1"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.team").exists())
           .andExpect(jsonPath("$.members").isArray());
    }

    @Test
    void deleteTeamMember_succeeds_for_logos_admin() throws Exception {
        mvc.perform(delete("/teams/2001/members/1001")
                .header("logos-key", "logos-admin-key"))
           .andExpect(status().isOk());
    }

    @Test
    void deleteTeam_succeeds_for_logos_admin() throws Exception {
        mvc.perform(delete("/teams/2001").header("logos-key", "logos-admin-key"))
           .andExpect(status().isOk());
    }

    @Test
    void deleteTeam_forbidden_for_developer() throws Exception {
        mvc.perform(delete("/teams/2001").header("logos-key", "dev-key-1"))
           .andExpect(status().isForbidden());
    }

    @Test
    void updateTeamLimits_succeeds_for_owner() throws Exception {
        mvc.perform(patch("/teams/2001")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"default_cloud_rpm_limit\":100}"))
           .andExpect(status().isOk());
    }

    @Test
    void updateTeamName_succeeds_for_owner() throws Exception {
        mvc.perform(patch("/teams/2001/name")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"name\":\"renamed-team\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.name").value("renamed-team"));
    }

    @Test
    void addMember_succeeds_for_owner() throws Exception {
        mvc.perform(post("/teams/2001/members")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"user_id\":1003,\"is_owner\":false}"))
           .andExpect(status().isOk());
    }

    @Test
    void updateMember_requires_logos_admin() throws Exception {
        mvc.perform(patch("/teams/2001/members/1001")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"is_owner\":false}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void updateMember_succeeds_for_logos_admin() throws Exception {
        mvc.perform(patch("/teams/2001/members/1001")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"is_owner\":false}"))
           .andExpect(status().isOk());
    }
}
