package de.tum.cit.aet.logos.logoswebservice.identity;

import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
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
           .andExpect(jsonPath("$.repo_slug").value("ls1intum/artemis"));
    }

    @Test
    void create_rejectsCaseVariantDuplicate() throws Exception {
        mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/ls1intum/Artemis\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.repo_slug").value("ls1intum/artemis"));

        mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/LS1INTUM/artemis.git\"}"))
           .andExpect(status().isConflict())
           .andExpect(jsonPath("$.detail", containsString("ls1intum/artemis")));
    }

    @Test
    void update_clearsPathFiltersWithEmptyArray() throws Exception {
        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("""
                    {
                      "repo_url": "https://github.com/ls1intum/path-clear",
                      "paths": ["logos"]
                    }
                    """))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.paths[0]").value("logos"))
           .andReturn();
        int linkId = mapper.readTree(created.getResponse().getContentAsString()).get("id").asInt();

        mvc.perform(patch("/admin/teams/2001/repositories/" + linkId)
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"paths\":[]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.paths").value(org.hamcrest.Matchers.nullValue()));
    }

    @Autowired
    org.springframework.jdbc.core.JdbcTemplate jdbc;

    @Test
    void update_slugChangeInvalidatesPriorAnalyses() throws Exception {
        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/ls1intum/old-repo\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.repo_slug").value("ls1intum/old-repo"))
           .andReturn();
        int linkId = mapper.readTree(created.getResponse().getContentAsString()).get("id").asInt();

        jdbc.update("""
            INSERT INTO ai_workflow_analyses
                (team_id, team_repository_id, commit_sha, status, source, finished_at)
            VALUES (2001, ?, 'abc', 'succeeded', 'heuristic', now())
            """, linkId);
        org.assertj.core.api.Assertions.assertThat(
            jdbc.queryForObject(
                "SELECT count(*) FROM ai_workflow_analyses WHERE team_repository_id = ?",
                Integer.class, linkId)).isEqualTo(1);

        mvc.perform(patch("/admin/teams/2001/repositories/" + linkId)
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/ls1intum/new-repo\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.repo_slug").value("ls1intum/new-repo"));

        org.assertj.core.api.Assertions.assertThat(
            jdbc.queryForObject(
                "SELECT count(*) FROM ai_workflow_analyses WHERE team_repository_id = ?",
                Integer.class, linkId)).isZero();
    }

    @Test
    void setRecommendationModel_storesAndClearsTheModel() throws Exception {
        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/ls1intum/model-pick\"}"))
           .andExpect(status().isOk())
           .andReturn();
        int linkId = mapper.readTree(created.getResponse().getContentAsString()).get("id").asInt();
        Integer analysisId = jdbc.queryForObject("""
            INSERT INTO ai_workflow_analyses
                (team_id, team_repository_id, commit_sha, status, source, finished_at)
            VALUES (2001, ?, 'abc', 'succeeded', 'agent', now())
            RETURNING id
            """, Integer.class, linkId);
        Integer recId = jdbc.queryForObject("""
            INSERT INTO ai_llm_call_recommendations
                (analysis_id, team_id, file_path, recommended_sla)
            VALUES (?, 2001, 'app/chat.py', 'ux-critical')
            RETURNING id
            """, Integer.class, analysisId);

        mvc.perform(put("/admin/teams/2001/recommendations/" + recId + "/model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model\":\"  openai/gpt-oss-120b \"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.detected_model").value("openai/gpt-oss-120b"))
           .andExpect(jsonPath("$.model_set_by_owner").value(true))
           .andExpect(jsonPath("$.review_status").value("pending"));

        // A review keeps the model; both write paths go through the same row lock.
        mvc.perform(post("/admin/teams/2001/recommendations/" + recId + "/review")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"action\":\"accept\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.review_status").value("accepted"))
           .andExpect(jsonPath("$.detected_model").value("openai/gpt-oss-120b"));

        mvc.perform(put("/admin/teams/2001/recommendations/" + recId + "/model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model\":\"\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.detected_model").doesNotExist());

        mvc.perform(put("/admin/teams/2001/recommendations/999999/model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model\":\"x\"}"))
           .andExpect(status().isNotFound());

        mvc.perform(put("/admin/teams/2001/recommendations/" + recId + "/model")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"model\":\"x\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void setWorkflowDiagram_storesOwnerEditAndProposalReview() throws Exception {
        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/ls1intum/diagram-edit\"}"))
           .andExpect(status().isOk())
           .andReturn();
        int linkId = mapper.readTree(created.getResponse().getContentAsString()).get("id").asInt();
        Integer analysisId = jdbc.queryForObject("""
            INSERT INTO ai_workflow_analyses
                (team_id, team_repository_id, commit_sha, status, source, finished_at)
            VALUES (2001, ?, 'abc', 'succeeded', 'agent', now())
            RETURNING id
            """, Integer.class, linkId);
        Integer workflowId = jdbc.queryForObject("""
            INSERT INTO ai_workflows
                (analysis_id, name, trigger_summary, diagram_mermaid, sort_order)
            VALUES (?, 'chat', 'user message', 'flowchart TD\n  A-->B', 0)
            RETURNING id
            """, Integer.class, analysisId);

        mvc.perform(put("/admin/teams/2001/workflows/" + workflowId + "/diagram")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"diagram_mermaid\":\"flowchart TD\\n  Owner-->Edit\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.diagram_mermaid").value("flowchart TD\n  Owner-->Edit"))
           .andExpect(jsonPath("$.diagram_set_by_owner").value(true))
           .andExpect(jsonPath("$.proposed_diagram_mermaid").doesNotExist());

        jdbc.update("""
            UPDATE ai_workflows
               SET proposed_diagram_mermaid = 'flowchart TD\n  Agent-->New'
             WHERE id = ?
            """, workflowId);

        mvc.perform(post("/admin/teams/2001/workflows/" + workflowId + "/diagram/proposal")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"action\":\"accept\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.diagram_mermaid").value("flowchart TD\n  Agent-->New"))
           .andExpect(jsonPath("$.diagram_set_by_owner").value(false))
           .andExpect(jsonPath("$.proposed_diagram_mermaid").doesNotExist());

        mvc.perform(put("/admin/teams/2001/workflows/" + workflowId + "/diagram")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"diagram_mermaid\":\"flowchart TD\\n  Owner-->Again\"}"))
           .andExpect(status().isOk());
        jdbc.update("""
            UPDATE ai_workflows
               SET proposed_diagram_mermaid = 'flowchart TD\n  Agent-->Other'
             WHERE id = ?
            """, workflowId);
        mvc.perform(post("/admin/teams/2001/workflows/" + workflowId + "/diagram/proposal")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"action\":\"dismiss\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.diagram_mermaid").value("flowchart TD\n  Owner-->Again"))
           .andExpect(jsonPath("$.diagram_set_by_owner").value(true))
           .andExpect(jsonPath("$.proposed_diagram_mermaid").doesNotExist());

        mvc.perform(put("/admin/teams/2001/workflows/999999/diagram")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"diagram_mermaid\":\"flowchart TD\\n  A\"}"))
           .andExpect(status().isNotFound());

        mvc.perform(put("/admin/teams/2001/workflows/" + workflowId + "/diagram")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"diagram_mermaid\":\"flowchart TD\\n  A\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void review_noApiKeyLeavesThePreviouslyLinkedKeyAlone() throws Exception {
        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/ls1intum/no-key\"}"))
           .andExpect(status().isOk())
           .andReturn();
        int linkId = mapper.readTree(created.getResponse().getContentAsString()).get("id").asInt();
        Integer analysisId = jdbc.queryForObject("""
            INSERT INTO ai_workflow_analyses
                (team_id, team_repository_id, commit_sha, status, source, finished_at)
            VALUES (2001, ?, 'abc', 'succeeded', 'agent', now())
            RETURNING id
            """, Integer.class, linkId);
        jdbc.update("UPDATE api_keys SET default_priority = 7 WHERE id = 3001");
        Integer recId = jdbc.queryForObject("""
            INSERT INTO ai_llm_call_recommendations
                (analysis_id, team_id, file_path, recommended_sla, api_key_id)
            VALUES (?, 2001, 'app/batch.py', 'ux-background', 3001)
            RETURNING id
            """, Integer.class, analysisId);

        mvc.perform(post("/admin/teams/2001/recommendations/" + recId + "/review")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"action\":\"accept\",\"no_api_key\":true}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.review_status").value("accepted"))
           .andExpect(jsonPath("$.api_key_id").doesNotExist());

        org.assertj.core.api.Assertions.assertThat(
            jdbc.queryForObject("SELECT default_priority FROM api_keys WHERE id = 3001", Integer.class))
            .isEqualTo(7);
    }

    @Test
    void queueAgentAnalysis_refusesASecondWhileOneIsInFlight() throws Exception {
        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/ls1intum/twice\"}"))
           .andExpect(status().isOk())
           .andReturn();
        int linkId = mapper.readTree(created.getResponse().getContentAsString()).get("id").asInt();

        mvc.perform(post("/admin/teams/2001/repositories/" + linkId + "/analyze/agent")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.status").value("queued"));
        mvc.perform(post("/admin/teams/2001/repositories/" + linkId + "/analyze/agent")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isConflict())
           .andExpect(jsonPath("$.detail", containsString("already queued or running")));
    }

    @Test
    void analyzeAll_queuesEveryLinkOnceAndIsLogosAdminOnly() throws Exception {
        for (String repo : new String[] {"all-a", "all-b"}) {
            mvc.perform(post("/admin/teams/2001/repositories")
                    .with(TestJwt.logosAdmin())
                    .contentType("application/json")
                    .content("{\"repo_url\":\"https://github.com/ls1intum/" + repo + "\"}"))
               .andExpect(status().isOk());
        }
        int links = jdbc.queryForObject("SELECT count(*) FROM team_repositories", Integer.class);

        mvc.perform(post("/admin/repositories/analyze").with(TestJwt.adminUser()))
           .andExpect(status().isForbidden());
        mvc.perform(post("/admin/repositories/analyze").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.queued").value(links))
           .andExpect(jsonPath("$.already_in_flight").value(0));
        mvc.perform(post("/admin/repositories/analyze").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.queued").value(0))
           .andExpect(jsonPath("$.already_in_flight").value(links));
    }

    @Test
    void reanalysis_showsTheLastReviewedDecisionAndRefusesEditsToSupersededRows() throws Exception {
        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/ls1intum/chain\"}"))
           .andExpect(status().isOk())
           .andReturn();
        int linkId = mapper.readTree(created.getResponse().getContentAsString()).get("id").asInt();
        // A (accepted) <- B (changed proposal, still pending) <- C (latest, pending)
        int[] analyses = new int[3];
        for (int i = 0; i < 3; i++) {
            analyses[i] = jdbc.queryForObject("""
                INSERT INTO ai_workflow_analyses
                    (team_id, team_repository_id, commit_sha, status, source, finished_at)
                VALUES (2001, ?, ?, 'succeeded', 'agent', now() - (? * interval '1 hour'))
                RETURNING id
                """, Integer.class, linkId, "c" + i, 3 - i);
        }
        Integer a = jdbc.queryForObject("""
            INSERT INTO ai_llm_call_recommendations
                (analysis_id, team_id, file_path, recommended_sla, review_status, confirmed_sla, reviewed_at)
            VALUES (?, 2001, 'app/chat.py', 'ux-critical', 'accepted', 'ux-critical', now())
            RETURNING id
            """, Integer.class, analyses[0]);
        Integer b = jdbc.queryForObject("""
            INSERT INTO ai_llm_call_recommendations
                (analysis_id, team_id, file_path, recommended_sla, previous_recommendation_id)
            VALUES (?, 2001, 'app/chat.py', 'ux-background', ?)
            RETURNING id
            """, Integer.class, analyses[1], a);
        Integer c = jdbc.queryForObject("""
            INSERT INTO ai_llm_call_recommendations
                (analysis_id, team_id, file_path, recommended_sla, previous_recommendation_id)
            VALUES (?, 2001, 'app/chat.py', 'ux-high-prio', ?)
            RETURNING id
            """, Integer.class, analyses[2], b);

        mvc.perform(get("/admin/teams/2001/workflows").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           // Only the latest analysis is up for review, and it shows A's decision.
           .andExpect(jsonPath("$.pending_recommendations[?(@.id == " + b + ")]").isEmpty())
           .andExpect(jsonPath("$.pending_recommendations[?(@.id == " + c + ")].previous.id").value(a))
           .andExpect(jsonPath("$.pending_recommendations[?(@.id == " + c + ")].previous.sla").value("ux-critical"));

        mvc.perform(put("/admin/teams/2001/recommendations/" + b + "/model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"model\":\"x\"}"))
           .andExpect(status().isConflict());
        mvc.perform(post("/admin/teams/2001/recommendations/" + b + "/review")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"action\":\"reject\"}"))
           .andExpect(status().isConflict());

        jdbc.update("UPDATE ai_llm_call_recommendations SET review_carried_over = TRUE WHERE id = ?", c);
        mvc.perform(post("/admin/teams/2001/recommendations/" + c + "/review")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"action\":\"accept\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.review_carried_over").value(false));
    }

    @Test
    void displayedRecommendationsStayEditableWhenAnAnalysisHasNoFinishTime() throws Exception {
        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/ls1intum/imported\"}"))
           .andExpect(status().isOk())
           .andReturn();
        int linkId = mapper.readTree(created.getResponse().getContentAsString()).get("id").asInt();
        Integer finished = jdbc.queryForObject("""
            INSERT INTO ai_workflow_analyses (team_id, team_repository_id, commit_sha, status, source, finished_at)
            VALUES (2001, ?, 'done', 'succeeded', 'agent', now()) RETURNING id
            """, Integer.class, linkId);
        // e.g. from an import: succeeded, but no finish time, and a higher id
        jdbc.update("""
            INSERT INTO ai_workflow_analyses (team_id, team_repository_id, commit_sha, status, source)
            VALUES (2001, ?, 'nofinish', 'succeeded', 'agent')
            """, linkId);
        Integer rec = jdbc.queryForObject("""
            INSERT INTO ai_llm_call_recommendations (analysis_id, team_id, file_path, recommended_sla)
            VALUES (?, 2001, 'app/x.py', 'ux-critical') RETURNING id
            """, Integer.class, finished);

        mvc.perform(get("/admin/teams/2001/workflows").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.pending_recommendations[?(@.id == " + rec + ")]").isNotEmpty());
        mvc.perform(post("/admin/teams/2001/recommendations/" + rec + "/review")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"action\":\"reject\"}"))
           .andExpect(status().isOk());
    }

    @Test
    void queueing_isRefusedByTheInFlightIndexEvenWithoutThePrecheck() throws Exception {
        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/ls1intum/racy\"}"))
           .andExpect(status().isOk())
           .andReturn();
        int linkId = mapper.readTree(created.getResponse().getContentAsString()).get("id").asInt();
        // Another writer (the agent runner's nightly pass) queued one meanwhile.
        jdbc.update("""
            INSERT INTO ai_workflow_analyses (team_id, team_repository_id, status, source, started_at)
            VALUES (2001, ?, 'running', 'agent', now())
            """, linkId);
        int sessionsBefore = jdbc.queryForObject("SELECT count(*) FROM agent_sessions", Integer.class);

        mvc.perform(post("/admin/teams/2001/repositories/" + linkId + "/analyze/agent")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isConflict());
        org.assertj.core.api.Assertions.assertThat(
            jdbc.queryForObject("SELECT count(*) FROM agent_sessions", Integer.class)).isEqualTo(sessionsBefore);
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
    void create_concurrentDuplicateReturnsConflict() throws Exception {
        // Two writers can both pass the precheck; the unique index must still
        // surface as 409 rather than an unhandled 500.
        var ready = new java.util.concurrent.CountDownLatch(2);
        var start = new java.util.concurrent.CountDownLatch(1);
        var outcomes = new java.util.concurrent.ConcurrentLinkedQueue<Integer>();

        Runnable postOnce = () -> {
            try {
                ready.countDown();
                start.await();
                int status = mvc.perform(post("/admin/teams/2001/repositories")
                        .with(TestJwt.logosAdmin())
                        .contentType("application/json")
                        .content("{\"repo_url\":\"https://github.com/ls1intum/race-repo\"}"))
                    .andReturn()
                    .getResponse()
                    .getStatus();
                outcomes.add(status);
            } catch (Exception e) {
                outcomes.add(-1);
            }
        };

        Thread a = new Thread(postOnce);
        Thread b = new Thread(postOnce);
        a.start();
        b.start();
        ready.await();
        start.countDown();
        a.join();
        b.join();

        org.assertj.core.api.Assertions.assertThat(outcomes)
            .containsExactlyInAnyOrder(200, 409);
    }

    @Test
    void delete_cancelsQueuedAnalysisSessionsForLink() throws Exception {
        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/acme/unlink-me\"}"))
           .andExpect(status().isOk())
           .andReturn();
        int linkId = mapper.readTree(created.getResponse().getContentAsString()).get("id").asInt();

        Integer workspaceId = jdbc.queryForObject("""
            INSERT INTO agent_workspaces (name, base_branch, volume_name, created_by, ephemeral)
            VALUES ('unlink-cancel-ws', 'main', 'unlink-cancel-vol', 'test', FALSE)
            RETURNING id
            """, Integer.class);
        Integer sessionId = jdbc.queryForObject("""
            INSERT INTO agent_sessions (
                workspace_id, task, status, created_by, open_pull_request, deploy_to_dev,
                screenshot_paths, no_push, team_repository_id, trigger_kind,
                repo_url, repo_slug
            ) VALUES (?, 'analyze', 'queued', 'test', FALSE, FALSE, '[]'::jsonb, TRUE, ?, 'analysis',
                      'https://github.com/acme/unlink-me.git', 'acme/unlink-me')
            RETURNING id
            """, Integer.class, workspaceId, linkId);

        mvc.perform(delete("/admin/teams/2001/repositories/" + linkId)
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk());

        java.util.Map<String, Object> row = jdbc.queryForMap(
            "SELECT status, error, team_repository_id FROM agent_sessions WHERE id = ?", sessionId);
        org.assertj.core.api.Assertions.assertThat(row.get("status")).isEqualTo("cancelled");
        org.assertj.core.api.Assertions.assertThat(row.get("team_repository_id")).isNull();
        org.assertj.core.api.Assertions.assertThat((String) row.get("error"))
            .contains("repository link");
    }

    @Test
    void delete_requestsRunnerCancelForRunningAndPausedAnalysis() throws Exception {
        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/acme/unlink-active\"}"))
           .andExpect(status().isOk())
           .andReturn();
        int linkId = mapper.readTree(created.getResponse().getContentAsString()).get("id").asInt();

        Integer wsRun = jdbc.queryForObject("""
            INSERT INTO agent_workspaces (name, base_branch, volume_name, created_by, ephemeral)
            VALUES ('unlink-run-ws', 'main', 'unlink-run-vol', 'test', FALSE)
            RETURNING id
            """, Integer.class);
        Integer wsPaused = jdbc.queryForObject("""
            INSERT INTO agent_workspaces (name, base_branch, volume_name, created_by, ephemeral)
            VALUES ('unlink-paused-ws', 'main', 'unlink-paused-vol', 'test', FALSE)
            RETURNING id
            """, Integer.class);
        Integer runningId = jdbc.queryForObject("""
            INSERT INTO agent_sessions (
                workspace_id, task, status, created_by, open_pull_request, deploy_to_dev,
                screenshot_paths, no_push, team_repository_id, trigger_kind,
                repo_url, repo_slug, container_id
            ) VALUES (?, 'analyze', 'running', 'test', FALSE, FALSE, '[]'::jsonb, TRUE, ?, 'analysis',
                      'https://github.com/acme/unlink-active.git', 'acme/unlink-active', 'ctr-run')
            RETURNING id
            """, Integer.class, wsRun, linkId);
        Integer pausedId = jdbc.queryForObject("""
            INSERT INTO agent_sessions (
                workspace_id, task, status, created_by, open_pull_request, deploy_to_dev,
                screenshot_paths, no_push, team_repository_id, trigger_kind,
                repo_url, repo_slug, container_id
            ) VALUES (?, 'analyze', 'paused', 'test', FALSE, FALSE, '[]'::jsonb, TRUE, ?, 'analysis',
                      'https://github.com/acme/unlink-active.git', 'acme/unlink-active', 'ctr-paused')
            RETURNING id
            """, Integer.class, wsPaused, linkId);

        mvc.perform(delete("/admin/teams/2001/repositories/" + linkId)
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk());

        for (Integer sessionId : java.util.List.of(runningId, pausedId)) {
            java.util.Map<String, Object> row = jdbc.queryForMap(
                "SELECT status, error, team_repository_id FROM agent_sessions WHERE id = ?", sessionId);
            // Still occupying until the agent runner honors cancel_requested.
            org.assertj.core.api.Assertions.assertThat(row.get("status"))
                .isIn("running", "paused");
            org.assertj.core.api.Assertions.assertThat(row.get("team_repository_id")).isNull();
            org.assertj.core.api.Assertions.assertThat((String) row.get("error"))
                .startsWith("cancel_requested:");
        }
    }

    @Test
    void delete_missingLinkReturns404() throws Exception {
        mvc.perform(delete("/admin/teams/2001/repositories/99999")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isNotFound());
    }
}
