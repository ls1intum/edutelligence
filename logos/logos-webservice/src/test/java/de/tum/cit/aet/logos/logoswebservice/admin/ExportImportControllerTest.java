package de.tum.cit.aet.logos.logoswebservice.admin;

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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

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
// RepoCredentialCrypto reads LOGOS_REPO_CREDENTIALS_* from the process env;
// SpringBootTest JVMs inherit the runner env — set DEV_FALLBACK in surefire
// or export it when running these tests locally.
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class ExportImportControllerTest {

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper objectMapper;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void export_requiresLogosAdmin() throws Exception {
        mvc.perform(post("/logosdb/export")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void export_logosAdminReturnsAllTables() throws Exception {
        mvc.perform(post("/logosdb/export")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").isMap())
           .andExpect(jsonPath("$.result.users").isArray())
           .andExpect(jsonPath("$.result.models").isArray())
           .andExpect(jsonPath("$.result.providers").isArray())
           .andExpect(jsonPath("$.result.team_repositories").isArray());
    }

    @Autowired
    org.springframework.jdbc.core.JdbcTemplate jdbc;

    @Test
    void importExport_roundtrip() throws Exception {
        mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("""
                    {
                      "repo_url": "https://github.com/ls1intum/edutelligence.git",
                      "branch": "develop",
                      "paths": ["logos"]
                    }
                    """))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.repo_slug").value("ls1intum/edutelligence"));

        Integer workspaceId = jdbc.queryForObject("""
            INSERT INTO agent_workspaces (name, base_branch, volume_name, created_by, ephemeral)
            VALUES ('export-import-preserve-ws', 'main', 'export-import-preserve-vol', 'test', FALSE)
            RETURNING id
            """, Integer.class);
        Integer repoLinkId = jdbc.queryForObject(
            "SELECT id FROM team_repositories WHERE team_id = 2001 AND repo_slug = 'ls1intum/edutelligence'",
            Integer.class);
        Integer sessionId = jdbc.queryForObject("""
            INSERT INTO agent_sessions (
                workspace_id, task, status, created_by, open_pull_request, deploy_to_dev,
                screenshot_paths, no_push, team_repository_id, trigger_kind
            ) VALUES (?, 'preserve me across import', 'queued', 'test', FALSE, FALSE, '[]'::jsonb, TRUE, ?, 'analysis')
            RETURNING id
            """, Integer.class, workspaceId, repoLinkId);
        jdbc.update("""
            INSERT INTO agent_events (session_id, kind, payload)
            VALUES (?, 'log', '{"message":"still here"}'::jsonb)
            """, sessionId);

        MvcResult exportResult = mvc.perform(post("/logosdb/export")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result.team_repositories.length()").value(1))
           .andExpect(jsonPath("$.result.team_repositories[0].paths").isArray())
           .andExpect(jsonPath("$.result.team_repositories[0].paths[0]").value("logos"))
           .andReturn();

        String exportBody = exportResult.getResponse().getContentAsString();
        @SuppressWarnings("unchecked")
        java.util.Map<String, Object> exportData =
            objectMapper.readValue(exportBody, java.util.Map.class);
        Object tableData = exportData.get("result");

        String importBody = objectMapper.writeValueAsString(
            java.util.Map.of("json_data", tableData));

        mvc.perform(post("/logosdb/import")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content(importBody))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Import successful"));

        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders
                .get("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1))
           .andExpect(jsonPath("$[0].repo_slug").value("ls1intum/edutelligence"))
           .andExpect(jsonPath("$[0].branch").value("develop"))
           .andExpect(jsonPath("$[0].paths[0]").value("logos"));

        Integer surviving = jdbc.queryForObject(
            "SELECT count(*) FROM agent_sessions WHERE id = ?", Integer.class, sessionId);
        org.assertj.core.api.Assertions.assertThat(surviving).isEqualTo(1);
        Integer survivingEvents = jdbc.queryForObject(
            "SELECT count(*) FROM agent_events WHERE session_id = ?", Integer.class, sessionId);
        org.assertj.core.api.Assertions.assertThat(survivingEvents).isEqualTo(1);
        Integer restoredLink = jdbc.queryForObject(
            "SELECT team_repository_id FROM agent_sessions WHERE id = ?", Integer.class, sessionId);
        org.assertj.core.api.Assertions.assertThat(restoredLink).isNotNull();
        String restoredSlug = jdbc.queryForObject(
            "SELECT repo_slug FROM team_repositories WHERE id = ?", String.class, restoredLink);
        org.assertj.core.api.Assertions.assertThat(restoredSlug).isEqualTo("ls1intum/edutelligence");
    }
}
