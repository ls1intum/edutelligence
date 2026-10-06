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

    @Test
    void import_clearsCollidingAnalysisSessionIdsAcrossRepositories() throws Exception {
        mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("""
                    {
                      "repo_url": "https://github.com/acme/repo-a.git",
                      "branch": "main",
                      "paths": ["src"]
                    }
                    """))
           .andExpect(status().isOk());
        mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("""
                    {
                      "repo_url": "https://github.com/acme/repo-b.git",
                      "branch": "main",
                      "paths": ["src"]
                    }
                    """))
           .andExpect(status().isOk());

        Integer repoA = jdbc.queryForObject(
            "SELECT id FROM team_repositories WHERE team_id = 2001 AND repo_slug = 'acme/repo-a'",
            Integer.class);
        Integer repoB = jdbc.queryForObject(
            "SELECT id FROM team_repositories WHERE team_id = 2001 AND repo_slug = 'acme/repo-b'",
            Integer.class);

        Integer workspaceId = jdbc.queryForObject("""
            INSERT INTO agent_workspaces (name, base_branch, volume_name, created_by, ephemeral)
            VALUES ('export-import-collision-ws', 'main', 'export-import-collision-vol', 'test', FALSE)
            RETURNING id
            """, Integer.class);
        // Local preserved session targets repo B.
        Integer sessionId = jdbc.queryForObject("""
            INSERT INTO agent_sessions (
                workspace_id, task, status, created_by, open_pull_request, deploy_to_dev,
                screenshot_paths, no_push, team_repository_id, trigger_kind
            ) VALUES (?, 'analyze B', 'queued', 'test', FALSE, FALSE, '[]'::jsonb, TRUE, ?, 'analysis')
            RETURNING id
            """, Integer.class, workspaceId, repoB);

        MvcResult exportResult = mvc.perform(post("/logosdb/export")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andReturn();

        @SuppressWarnings("unchecked")
        java.util.Map<String, Object> exportEnvelope =
            objectMapper.readValue(exportResult.getResponse().getContentAsString(), java.util.Map.class);
        @SuppressWarnings("unchecked")
        java.util.Map<String, Object> tableData =
            (java.util.Map<String, Object>) exportEnvelope.get("result");

        // Imported analysis for repo A reuses the local session id that still
        // analyzes repo B — must be cleared on import.
        @SuppressWarnings("unchecked")
        java.util.List<java.util.Map<String, Object>> analyses =
            (java.util.List<java.util.Map<String, Object>>) tableData.get("ai_workflow_analyses");
        analyses.add(new java.util.LinkedHashMap<>(java.util.Map.of(
            "id", 9001,
            "team_id", 2001,
            "team_repository_id", repoA,
            "commit_sha", "deadbeef",
            "status", "queued",
            "source", "agent",
            "agent_session_id", sessionId,
            "started_at", "2026-01-01T00:00:00Z"
        )));
        analyses.get(analyses.size() - 1).put("error", null);
        analyses.get(analyses.size() - 1).put("finished_at", null);
        // Matching association (same session + repo B) must survive.
        analyses.add(new java.util.LinkedHashMap<>(java.util.Map.of(
            "id", 9002,
            "team_id", 2001,
            "team_repository_id", repoB,
            "commit_sha", "cafebabe",
            "status", "queued",
            "source", "agent",
            "agent_session_id", sessionId,
            "started_at", "2026-01-01T00:00:00Z"
        )));
        analyses.get(analyses.size() - 1).put("error", null);
        analyses.get(analyses.size() - 1).put("finished_at", null);

        String importBody = objectMapper.writeValueAsString(
            java.util.Map.of("json_data", tableData));
        mvc.perform(post("/logosdb/import")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content(importBody))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Import successful"));

        Integer restoredB = jdbc.queryForObject(
            "SELECT team_repository_id FROM agent_sessions WHERE id = ?", Integer.class, sessionId);
        org.assertj.core.api.Assertions.assertThat(restoredB).isEqualTo(repoB);

        java.util.Map<String, Object> mismatched = jdbc.queryForMap(
            "SELECT agent_session_id, status, error FROM ai_workflow_analyses WHERE id = 9001");
        org.assertj.core.api.Assertions.assertThat(mismatched.get("agent_session_id")).isNull();
        org.assertj.core.api.Assertions.assertThat(mismatched.get("status")).isEqualTo("failed");
        org.assertj.core.api.Assertions.assertThat((String) mismatched.get("error"))
            .contains("imported session association cleared");

        java.util.Map<String, Object> matched = jdbc.queryForMap(
            "SELECT agent_session_id, status FROM ai_workflow_analyses WHERE id = 9002");
        org.assertj.core.api.Assertions.assertThat(matched.get("agent_session_id"))
            .isEqualTo(sessionId);
        org.assertj.core.api.Assertions.assertThat(matched.get("status")).isEqualTo("queued");
    }

    @Test
    void import_acceptsPre044ExportMissingNewJsonbColumns() throws Exception {
        mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("""
                    {
                      "repo_url": "https://github.com/acme/pre044.git",
                      "branch": "main",
                      "paths": ["src"]
                    }
                    """))
           .andExpect(status().isOk());

        Integer repoId = jdbc.queryForObject(
            "SELECT id FROM team_repositories WHERE team_id = 2001 AND repo_slug = 'acme/pre044'",
            Integer.class);

        MvcResult exportResult = mvc.perform(post("/logosdb/export")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andReturn();

        @SuppressWarnings("unchecked")
        java.util.Map<String, Object> exportEnvelope =
            objectMapper.readValue(exportResult.getResponse().getContentAsString(), java.util.Map.class);
        @SuppressWarnings("unchecked")
        java.util.Map<String, Object> tableData =
            (java.util.Map<String, Object>) exportEnvelope.get("result");

        @SuppressWarnings("unchecked")
        java.util.List<java.util.Map<String, Object>> models =
            (java.util.List<java.util.Map<String, Object>>) tableData.get("models");
        org.assertj.core.api.Assertions.assertThat(models).isNotEmpty();
        for (java.util.Map<String, Object> model : models) {
            model.remove("profile_ratings");
        }

        @SuppressWarnings("unchecked")
        java.util.List<java.util.Map<String, Object>> analyses =
            (java.util.List<java.util.Map<String, Object>>) tableData.get("ai_workflow_analyses");
        java.util.Map<String, Object> analysis = new java.util.LinkedHashMap<>();
        analysis.put("id", 9101);
        analysis.put("team_id", 2001);
        analysis.put("team_repository_id", repoId);
        analysis.put("commit_sha", "pre044sha");
        analysis.put("status", "succeeded");
        analysis.put("source", "heuristic");
        analysis.put("agent_session_id", null);
        analysis.put("error", null);
        analysis.put("started_at", "2026-01-01T00:00:00Z");
        analysis.put("finished_at", "2026-01-01T00:01:00Z");
        analyses.add(analysis);

        @SuppressWarnings("unchecked")
        java.util.List<java.util.Map<String, Object>> workflows =
            (java.util.List<java.util.Map<String, Object>>) tableData.get("ai_workflows");
        workflows.add(new java.util.LinkedHashMap<>(java.util.Map.of(
            "id", 9102,
            "analysis_id", 9101,
            "name", "chat",
            "trigger_summary", "user",
            "diagram_mermaid", "flowchart TD\n  A-->B",
            "sort_order", 0
        )));

        @SuppressWarnings("unchecked")
        java.util.List<java.util.Map<String, Object>> recommendations =
            (java.util.List<java.util.Map<String, Object>>) tableData.get("ai_llm_call_recommendations");
        java.util.Map<String, Object> rec = new java.util.LinkedHashMap<>();
        rec.put("id", 9103);
        rec.put("analysis_id", 9101);
        rec.put("workflow_id", 9102);
        rec.put("team_id", 2001);
        rec.put("file_path", "src/app.py");
        rec.put("start_line", 1);
        rec.put("end_line", 10);
        rec.put("code_url", null);
        rec.put("detected_model", "gpt-fast");
        rec.put("api_key_id", null);
        rec.put("recommended_sla", "ux-critical");
        // Pre-044: no objective_priority / confirmed_objective_priority
        rec.put("confidence", 0.9);
        rec.put("justification", "interactive");
        rec.put("traffic_flags", java.util.Map.of("night_heavy", false));
        rec.put("review_status", "pending");
        rec.put("confirmed_sla", null);
        rec.put("reviewed_by", null);
        rec.put("reviewed_at", null);
        recommendations.add(rec);
        // Exports from before workflow steps, benchmarks and key queue ranks.
        tableData.remove("ai_workflow_steps");
        tableData.remove("ai_workflow_benchmarks");
        tableData.remove("application_key_queue_ranks");

        String importBody = objectMapper.writeValueAsString(
            java.util.Map.of("json_data", tableData));
        mvc.perform(post("/logosdb/import")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content(importBody))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Import successful"));

        Integer nullProfiles = jdbc.queryForObject(
            "SELECT count(*) FROM models WHERE profile_ratings IS NULL", Integer.class);
        org.assertj.core.api.Assertions.assertThat(nullProfiles).isZero();

        String priorityJson = jdbc.queryForObject(
            "SELECT objective_priority::text FROM ai_llm_call_recommendations WHERE id = 9103",
            String.class);
        org.assertj.core.api.Assertions.assertThat(priorityJson)
            .contains("latency")
            .contains("quality")
            .contains("price");

        String workflowStatus = jdbc.queryForObject(
            "SELECT status FROM ai_workflows WHERE id = 9102", String.class);
        org.assertj.core.api.Assertions.assertThat(workflowStatus).isEqualTo("active");
    }
}
