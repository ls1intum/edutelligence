package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/**
 * Direct-cloud attribution: headers resolve to workflow/step/SLO and land on
 * the reserved {@code log_entry} row the gateway writes before forwarding.
 */
@SpringBootTest
@Testcontainers
class GatewayWorkflowAttributionTest {

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    GatewayWorkflowAttributionResolver resolver;

    @Autowired
    GatewayCloudAccounting accounting;

    @MockitoBean
    JwtDecoder jwtDecoder;

    @Container
    @SuppressWarnings("resource")
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17")
            .withDatabaseName("logosdb")
            .withUsername("postgres")
            .withPassword("root");

    @DynamicPropertySource
    @SuppressWarnings("unused")
    static void configureProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
        registry.add("spring.datasource.driver-class-name", () -> "org.postgresql.Driver");
        registry.add("spring.liquibase.enabled", () -> "true");
        registry.add("spring.liquibase.change-log", () -> "classpath:liquibase/changelog/master.xml");
        registry.add("spring.jpa.hibernate.ddl-auto", () -> "validate");
    }

    private static final AtomicInteger SEQ = new AtomicInteger(1);
    private static final byte[] REQUEST_BODY =
        "{\"model\":\"m\",\"messages\":[]}".getBytes(StandardCharsets.UTF_8);

    @Test
    void resolveAndReserve_writesWorkflowSloAttributionOntoLogEntry() {
        Fixture f = seedFixtureWithStep("checkout-score", "ux-critical");

        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("X-Logos-Workflow-Tag", "checkout-score");
        request.addHeader("X-Logos-SLO", "ux-high-prio");

        GatewayRequestAttribution attr = resolver.resolve(request, f.teamId());
        assertThat(attr.workflowTag()).isEqualTo("checkout-score");
        assertThat(attr.workflowId()).isEqualTo(f.workflowId());
        assertThat(attr.workflowStepId()).isEqualTo(f.stepId());
        // Explicit header SLO wins over the step's recommended SLO.
        assertThat(attr.requestSlo()).isEqualTo("ux-high-prio");

        Integer logId = accounting.admitAndReserve(
            f.key(), f.deployment(), REQUEST_BODY, "BILLING", attr);
        assertThat(logId).isNotNull();

        Map<String, Object> row = jdbc.queryForMap("""
            SELECT workflow_tag, workflow_id, workflow_step_id, request_slo
              FROM log_entry WHERE id = ?
            """, logId);
        assertThat(row.get("workflow_tag")).isEqualTo("checkout-score");
        assertThat(((Number) row.get("workflow_id")).intValue()).isEqualTo(f.workflowId());
        assertThat(((Number) row.get("workflow_step_id")).intValue()).isEqualTo(f.stepId());
        assertThat(row.get("request_slo")).isEqualTo("ux-high-prio");
    }

    @Test
    void resolve_dropsInvalidSloAndKeepsTeamScopedTag() {
        Fixture f = seedFixtureWithStep("team-only-tag", "ux-background");

        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("X-Logos-Workflow-Tag", "team-only-tag");
        request.addHeader("X-Logos-SLO", "not-a-real-slo");

        GatewayRequestAttribution attr = resolver.resolve(request, f.teamId());
        assertThat(attr.workflowId()).isEqualTo(f.workflowId());
        assertThat(attr.workflowStepId()).isEqualTo(f.stepId());
        // Invalid header is ignored; the step's recommended SLO fills in.
        assertThat(attr.requestSlo()).isEqualTo("ux-background");

        // A tag that belongs to another team must not resolve for this key.
        MockHttpServletRequest foreign = new MockHttpServletRequest();
        foreign.addHeader("X-Logos-Workflow-Tag", "team-only-tag");
        GatewayRequestAttribution missed = resolver.resolve(foreign, f.teamId() + 9999);
        assertThat(missed.workflowId()).isNull();
        assertThat(missed.workflowStepId()).isNull();
        assertThat(missed.workflowTag()).isEqualTo("team-only-tag");
    }

    private record Fixture(
        int teamId, int workflowId, int stepId,
        GatewayKey key, GatewayDeployment deployment
    ) {
    }

    private Fixture seedFixtureWithStep(String stepTag, String recommendedSlo) {
        int modelId = jdbc.queryForObject(
            "INSERT INTO models (name) VALUES (?) RETURNING id",
            Integer.class, "m-" + SEQ.getAndIncrement());
        int providerId = jdbc.queryForObject(
            "INSERT INTO providers (name, base_url, provider_type, cloud_provider_type, auth_name, auth_format) "
            + "VALUES (?, 'http://x', 'cloud', 'openai'::cloud_provider_type_enum, 'Authorization', 'Bearer %s') "
            + "RETURNING id",
            Integer.class, "p-" + SEQ.getAndIncrement());
        int teamId = jdbc.queryForObject(
            "INSERT INTO teams (name, default_monthly_budget_micro_cents, team_monthly_budget_micro_cents) "
            + "VALUES (?, 1000000000, 1000000000) RETURNING id",
            Integer.class, "t-" + SEQ.getAndIncrement());
        int apiKeyId = jdbc.queryForObject(
            "INSERT INTO api_keys (key_value, name, team_id, key_type, log) "
            + "VALUES (?, ?, ?, ?::api_key_type_enum, 'BILLING'::logging_enum) RETURNING id",
            Integer.class, "lg-" + SEQ.getAndIncrement(), "k-" + SEQ.get(), teamId,
            ApiKeyType.application.name());
        int repoN = SEQ.getAndIncrement();
        int linkId = jdbc.queryForObject("""
            INSERT INTO team_repositories (team_id, repo_url, repo_slug)
            VALUES (?, ?, ?) RETURNING id
            """, Integer.class, teamId,
            "https://github.com/example/repo-" + repoN,
            "example/repo-" + repoN);
        int analysisId = jdbc.queryForObject("""
            INSERT INTO ai_workflow_analyses
                (team_id, team_repository_id, commit_sha, status, source, finished_at)
            VALUES (?, ?, 'abc', 'succeeded', 'agent', now())
            RETURNING id
            """, Integer.class, teamId, linkId);
        int workflowId = jdbc.queryForObject("""
            INSERT INTO ai_workflows (analysis_id, name, diagram_mermaid, tag)
            VALUES (?, 'checkout', 'flowchart TD', 'checkout')
            RETURNING id
            """, Integer.class, analysisId);
        int stepId = jdbc.queryForObject("""
            INSERT INTO ai_workflow_steps (workflow_id, name, tag, recommended_slo)
            VALUES (?, 'score', ?, ?)
            RETURNING id
            """, Integer.class, workflowId, stepTag, recommendedSlo);

        GatewayKey key = new GatewayKey(apiKeyId, "lg-x", "k", ApiKeyType.application,
            teamId, null, "test", false, null, 0, "BILLING");
        GatewayDeployment deployment = new GatewayDeployment(modelId, "m", providerId, "p",
            "cloud", "openai", "http://x", "/v1/chat/completions",
            "Authorization", "Bearer %s", "sk-x", "BILLING", null);
        return new Fixture(teamId, workflowId, stepId, key, deployment);
    }
}
