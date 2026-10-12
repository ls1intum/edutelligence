package de.tum.cit.aet.logos.logoswebservice.identity;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.Map;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    "logos.auth.roles.logos-admin=itg-admin",
    "logos.auth.roles.app-admin=chair-member",
    "logos.auth.sync-debounce-minutes=5",
    "logos.orchestrator.url=",
    "logos.orchestrator.internal-secret=test-internal-secret"
})
@Sql(scripts = {"/sql/seed-identity.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class InternalSessionApiKeyControllerTest {

    @Autowired MockMvc mvc;
    @Autowired NamedParameterJdbcTemplate jdbc;
    @Autowired ObjectMapper mapper;
    @MockitoBean JwtDecoder jwtDecoder;

    private int createStartingSession() {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        Integer workspaceId = jdbc.getJdbcOperations().queryForObject("""
            INSERT INTO agent_workspaces (name, base_branch, volume_name, created_by, ephemeral)
            VALUES (?, 'main', ?, 'test', FALSE)
            RETURNING id
            """, Integer.class, "session-key-ws-" + suffix, "session-key-vol-" + suffix);
        return jdbc.getJdbcOperations().queryForObject("""
            INSERT INTO agent_sessions (
                workspace_id, task, status, created_by, open_pull_request, deploy_to_dev,
                screenshot_paths, no_push
            ) VALUES (?, 'mint-key', 'starting', 'test', FALSE, FALSE, '[]'::jsonb, TRUE)
            RETURNING id
            """, Integer.class, workspaceId);
    }

    private String parentKeyValue() {
        return jdbc.queryForObject(
            "SELECT key_value FROM api_keys WHERE is_active = true AND parent_api_key_id IS NULL ORDER BY id LIMIT 1",
            Map.of(),
            String.class);
    }

    @Test
    void mintRequiresInternalSecret() throws Exception {
        int sessionId = createStartingSession();
        mvc.perform(post("/internal/session_api_keys")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"parent_key_value\":\"lg-seed\",\"session_id\":" + sessionId + "}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void mintAndRevokeSessionKey() throws Exception {
        String parent = parentKeyValue();
        assertThat(parent).isNotBlank();
        int sessionId = createStartingSession();

        MvcResult minted = mvc.perform(post("/internal/session_api_keys")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"parent_key_value\":\"" + parent
                    + "\",\"name\":\"agent-session-test\",\"session_id\":" + sessionId + "}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.id").isNumber())
           .andExpect(jsonPath("$.key_value").isString())
           .andExpect(jsonPath("$.parent_api_key_id").isNumber())
           .andExpect(jsonPath("$.expires_at").doesNotExist())
           .andReturn();

        Map<?, ?> body = mapper.readValue(minted.getResponse().getContentAsString(), Map.class);
        int childId = ((Number) body.get("id")).intValue();

        Integer linked = jdbc.queryForObject(
            "SELECT session_api_key_id FROM agent_sessions WHERE id = :id",
            Map.of("id", sessionId),
            Integer.class);
        assertThat(linked).isEqualTo(childId);

        Integer audit = jdbc.queryForObject(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'api_key.agent_minted' AND target_id = :id",
            Map.of("id", String.valueOf(childId)),
            Integer.class);
        assertThat(audit).isEqualTo(1);

        mvc.perform(post("/internal/session_api_keys/" + childId + "/revoke")
                .header("Authorization", "Bearer test-internal-secret"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.status").value("revoked"));

        Boolean active = jdbc.queryForObject(
            "SELECT is_active FROM api_keys WHERE id = :id",
            Map.of("id", childId),
            Boolean.class);
        assertThat(active).isFalse();

        Integer revokeAudit = jdbc.queryForObject(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'api_key.agent_revoked' AND target_id = :id",
            Map.of("id", String.valueOf(childId)),
            Integer.class);
        assertThat(revokeAudit).isEqualTo(1);
    }

    @Test
    void mintWithoutSessionIdIsRejected() throws Exception {
        String parent = parentKeyValue();
        mvc.perform(post("/internal/session_api_keys")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"parent_key_value\":\"" + parent + "\",\"name\":\"missing-session\"}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void mintRollsBackKeyWhenSessionCannotBeLinked() throws Exception {
        String parent = parentKeyValue();
        int before = jdbc.queryForObject(
            "SELECT COUNT(*) FROM api_keys WHERE parent_api_key_id IS NOT NULL",
            Map.of(),
            Integer.class);

        mvc.perform(post("/internal/session_api_keys")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"parent_key_value\":\"" + parent
                    + "\",\"name\":\"orphan-guard\",\"session_id\":999999001}"))
           .andExpect(status().isBadRequest());

        int after = jdbc.queryForObject(
            "SELECT COUNT(*) FROM api_keys WHERE parent_api_key_id IS NOT NULL",
            Map.of(),
            Integer.class);
        assertThat(after).isEqualTo(before);
    }

    @Test
    void standingKeyCannotBeRevokedThroughTheRunnerEndpoint() throws Exception {
        Integer standingId = jdbc.queryForObject(
            "SELECT id FROM api_keys WHERE is_active = true AND parent_api_key_id IS NULL ORDER BY id LIMIT 1",
            Map.of(),
            Integer.class);

        mvc.perform(post("/internal/session_api_keys/" + standingId + "/revoke")
                .header("Authorization", "Bearer test-internal-secret"))
           .andExpect(status().isNotFound());

        Boolean active = jdbc.queryForObject(
            "SELECT is_active FROM api_keys WHERE id = :id",
            Map.of("id", standingId),
            Boolean.class);
        assertThat(active).isTrue();
    }

    @Test
    void mintedKeyCannotMintFurtherKeys() throws Exception {
        String parent = parentKeyValue();
        int sessionId = createStartingSession();

        MvcResult minted = mvc.perform(post("/internal/session_api_keys")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"parent_key_value\":\"" + parent + "\",\"session_id\":" + sessionId + "}"))
           .andExpect(status().isOk())
           .andReturn();
        Map<?, ?> body = mapper.readValue(minted.getResponse().getContentAsString(), Map.class);
        String childValue = (String) body.get("key_value");

        int otherSession = createStartingSession();
        mvc.perform(post("/internal/session_api_keys")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"parent_key_value\":\"" + childValue + "\",\"session_id\":" + otherSession + "}"))
           .andExpect(status().isBadRequest());
    }
}
