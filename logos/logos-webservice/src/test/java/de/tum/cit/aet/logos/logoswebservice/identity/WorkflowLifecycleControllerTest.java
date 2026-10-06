package de.tum.cit.aet.logos.logoswebservice.identity;

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
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

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
class WorkflowLifecycleControllerTest {

    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;
    @MockitoBean JwtDecoder jwtDecoder;

    private final ObjectMapper mapper = new ObjectMapper();

    private int[] seedWorkflowWithStep() throws Exception {
        MvcResult created = mvc.perform(post("/admin/teams/2001/repositories")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"repo_url\":\"https://github.com/ls1intum/workflow-lifecycle\"}"))
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
            INSERT INTO ai_workflows (analysis_id, name, diagram_mermaid, tag)
            VALUES (?, 'checkout', 'flowchart TD', 'checkout')
            RETURNING id
            """, Integer.class, analysisId);
        Integer stepId = jdbc.queryForObject("""
            INSERT INTO ai_workflow_steps (workflow_id, name, tag, recommended_sla)
            VALUES (?, 'score', 'checkout-score', 'ux-critical')
            RETURNING id
            """, Integer.class, workflowId);
        return new int[] {workflowId, stepId};
    }

    @Test
    void workflowLifecycle_deprecateSoftDeleteAndRestore() throws Exception {
        int workflowId = seedWorkflowWithStep()[0];

        mvc.perform(patch("/admin/teams/2001/workflows/" + workflowId)
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"status\":\"Deprecated\",\"tag\":\" Checkout.Pay \"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.status").value("deprecated"))
           .andExpect(jsonPath("$.tag").value("checkoutpay"))
           .andExpect(jsonPath("$.steps[0].name").value("score"));

        mvc.perform(patch("/admin/teams/2001/workflows/" + workflowId)
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"status\":\"archived\"}"))
           .andExpect(status().isBadRequest());

        mvc.perform(patch("/admin/teams/2001/workflows/" + workflowId)
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"deleted\":true}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.status").value("ignored"))
           .andExpect(jsonPath("$.deleted_at").isNotEmpty());

        mvc.perform(get("/admin/teams/2001/workflows").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.repositories[0].workflows").isEmpty());

        mvc.perform(patch("/admin/teams/2001/workflows/" + workflowId)
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"deleted\":false}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.status").value("active"))
           .andExpect(jsonPath("$.deleted_at").doesNotExist());
    }

    @Test
    void workflowEdits_refuseASupersededAnalysis() throws Exception {
        int[] ids = seedWorkflowWithStep();
        jdbc.update("""
            INSERT INTO ai_workflow_analyses
                (team_id, team_repository_id, commit_sha, status, source, finished_at)
            SELECT team_id, team_repository_id, 'newer', 'succeeded', 'agent', now() + interval '1 minute'
              FROM ai_workflow_analyses
             WHERE id = (SELECT analysis_id FROM ai_workflows WHERE id = ?)
            """, ids[0]);

        mvc.perform(patch("/admin/teams/2001/workflows/" + ids[0])
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"status\":\"ignored\"}"))
           .andExpect(status().isConflict());
        mvc.perform(patch("/admin/teams/2001/workflow-steps/" + ids[1])
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"confirmed_sla\":\"ux-background\"}"))
           .andExpect(status().isConflict());
    }

    @Test
    void workflowStep_confirmSlaValidatesAndIsTeamScoped() throws Exception {
        int stepId = seedWorkflowWithStep()[1];

        mvc.perform(patch("/admin/teams/2001/workflow-steps/" + stepId)
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"confirmed_sla\":\"ux-background\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.recommended_sla").value("ux-critical"))
           .andExpect(jsonPath("$.confirmed_sla").value("ux-background"));

        mvc.perform(patch("/admin/teams/2001/workflow-steps/" + stepId)
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"confirmed_sla\":\"urgent\"}"))
           .andExpect(status().isBadRequest());

        mvc.perform(patch("/admin/teams/2001/workflow-steps/" + stepId)
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"tag\":\"!!!\"}"))
           .andExpect(status().isBadRequest());

        // The workflow's own tag is taken within the team.
        mvc.perform(patch("/admin/teams/2001/workflow-steps/" + stepId)
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"tag\":\"checkout\"}"))
           .andExpect(status().isConflict());

        // Another team's id in the path does not reach this team's step.
        mvc.perform(patch("/admin/teams/2002/workflow-steps/" + stepId)
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"confirmed_sla\":\"ux-critical\"}"))
           .andExpect(status().isNotFound());

        mvc.perform(patch("/admin/teams/2001/workflow-steps/" + stepId)
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"confirmed_sla\":\"ux-critical\"}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void proposeTaggingPr_isLogosAdminOnlyAndPersistsMissingTags() throws Exception {
        int[] ids = seedWorkflowWithStep();
        jdbc.update("UPDATE ai_workflows SET tag = NULL WHERE id = ?", ids[0]);
        jdbc.update("UPDATE ai_workflow_steps SET tag = NULL WHERE id = ?", ids[1]);
        // A same-named workflow already holds the tags generation would pick first.
        Integer sibling = jdbc.queryForObject("""
            INSERT INTO ai_workflows (analysis_id, name, diagram_mermaid, tag)
            SELECT analysis_id, 'checkout', 'flowchart TD', 'checkout' FROM ai_workflows WHERE id = ?
            RETURNING id
            """, Integer.class, ids[0]);
        jdbc.update("""
            INSERT INTO ai_workflow_steps (workflow_id, name, tag, recommended_sla)
            VALUES (?, 'score', 'checkout-2-score', 'ux-background')
            """, sibling);

        // An owning App Admin may not aim the agent's GitHub account at a repository.
        mvc.perform(post("/admin/teams/2001/workflows/" + ids[0] + "/propose-tagging-pr")
                .with(TestJwt.adminUser()))
           .andExpect(status().isForbidden());

        MvcResult queued = mvc.perform(post("/admin/teams/2001/workflows/" + ids[0] + "/propose-tagging-pr")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.status").value("queued"))
           .andReturn();
        int sessionId = mapper.readTree(queued.getResponse().getContentAsString())
            .get("agent_session_id").asInt();

        String workflowTag = jdbc.queryForObject(
            "SELECT tag FROM ai_workflows WHERE id = ?", String.class, ids[0]);
        String stepTag = jdbc.queryForObject(
            "SELECT tag FROM ai_workflow_steps WHERE id = ?", String.class, ids[1]);
        org.assertj.core.api.Assertions.assertThat(workflowTag).isEqualTo("checkout-2");
        org.assertj.core.api.Assertions.assertThat(stepTag).isEqualTo("checkout-2-score-2");
        String task = jdbc.queryForObject(
            "SELECT task FROM agent_sessions WHERE id = ? AND trigger_kind = 'workflow-tagging'",
            String.class, sessionId);
        org.assertj.core.api.Assertions.assertThat(task)
            .contains("Workflow tag (X-Logos-Workflow-Tag): checkout-2")
            .contains("tag=checkout-2-score-2");
    }

    @Test
    void applicationKeyQueueRanks_replaceValidatesAndIsLogosAdminOnly() throws Exception {
        mvc.perform(put("/admin/application-key-queue-ranks")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"api_key_ids\":[3002]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$[0].api_key_id").value(3002))
           .andExpect(jsonPath("$[0].rank").value(1));

        // Developer keys cannot be ranked; duplicates are rejected.
        mvc.perform(put("/admin/application-key-queue-ranks")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"api_key_ids\":[3001]}"))
           .andExpect(status().isBadRequest());
        mvc.perform(put("/admin/application-key-queue-ranks")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"api_key_ids\":[3002, 3002]}"))
           .andExpect(status().isBadRequest());

        mvc.perform(get("/admin/application-key-queue-ranks").with(TestJwt.adminUser()))
           .andExpect(status().isForbidden());

        mvc.perform(put("/admin/application-key-queue-ranks")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"api_key_ids\":[]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").isEmpty());
    }
}
