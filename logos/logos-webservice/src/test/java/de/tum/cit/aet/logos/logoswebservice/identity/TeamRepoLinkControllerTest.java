package de.tum.cit.aet.logos.logoswebservice.identity;

import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

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
import org.springframework.test.web.servlet.MvcResult;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

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
class TeamRepoLinkControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void list_requiresAppAdminOrAbove() throws Exception {
        mvc.perform(get("/admin/teams/2001/repositories").with(TestJwt.testUser()))
           .andExpect(status().isForbidden());
    }

    @Test
    void list_forbiddenForNonOwnerAppAdmin() throws Exception {
        // adminuser owns team 2001; creating another team they do not own is
        // awkward here, so use logos admin to create a second team and then
        // hit it as adminuser (owner of 2001 only).
        MvcResult created = mvc.perform(post("/teams")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"repo-link-foreign\",\"owner_ids\":[1003]}"))
           .andExpect(status().isOk())
           .andReturn();
        int foreignTeamId = mapper.readTree(created.getResponse().getContentAsString()).get("id").asInt();

        mvc.perform(get("/admin/teams/" + foreignTeamId + "/repositories")
                .with(TestJwt.adminUser()))
           .andExpect(status().isForbidden());

        mvc.perform(delete("/teams/" + foreignTeamId).with(TestJwt.logosAdmin()))
           .andExpect(status().isOk());
    }

    @Test
    void crud_logosAdminFullCycle() throws Exception {
        mvc.perform(get("/admin/teams/2001/repositories").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isArray())
           .andExpect(jsonPath("$.length()").value(0));

        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("""
                    {
                      "repo_url": "https://github.com/ls1intum/edutelligence.git",
                      "branch": "main",
                      "paths": ["logos/logos-ui", "logos/logos-agent"]
                    }
                    """))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.repo_slug").value("ls1intum/edutelligence"))
           .andExpect(jsonPath("$.branch").value("main"))
           .andExpect(jsonPath("$.paths[0]").value("logos/logos-ui"))
           .andExpect(jsonPath("$.paths[1]").value("logos/logos-agent"))
           .andReturn();

        JsonNode link = mapper.readTree(created.getResponse().getContentAsString());
        int linkId = link.get("id").asInt();

        mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"git@github.com:ls1intum/edutelligence.git\"}"))
           .andExpect(status().isConflict());

        mvc.perform(patch("/admin/teams/2001/repositories/" + linkId)
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"branch\":\"develop\",\"paths\":[\"logos\"]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.branch").value("develop"))
           .andExpect(jsonPath("$.paths[0]").value("logos"));

        mvc.perform(delete("/admin/teams/2001/repositories/" + linkId)
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.message").value("Repository link deleted"));

        mvc.perform(get("/admin/teams/2001/repositories").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void create_ownerAppAdminSucceeds() throws Exception {
        mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/ls1intum/Artemis\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.repo_slug").value("ls1intum/Artemis"));
    }

    @Test
    void create_rejectsNonGithubUrl() throws Exception {
        mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://gitlab.com/ls1intum/edutelligence\"}"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.detail", containsString("GitHub")));
    }

    @Test
    void delete_missingLinkReturns404() throws Exception {
        mvc.perform(delete("/admin/teams/2001/repositories/99999")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isNotFound());
    }
}
