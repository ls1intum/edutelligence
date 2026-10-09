package de.tum.cit.aet.logos.logoswebservice.identity;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.Map;

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

    @Test
    void mintRequiresInternalSecret() throws Exception {
        mvc.perform(post("/internal/session_api_keys")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"parent_key_value\":\"lg-seed\",\"ttl_seconds\":60}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void mintAndRevokeSessionKey() throws Exception {
        String parent = jdbc.queryForObject(
            "SELECT key_value FROM api_keys WHERE is_active = true AND parent_api_key_id IS NULL ORDER BY id LIMIT 1",
            Map.of(),
            String.class);
        assertThat(parent).isNotBlank();

        MvcResult minted = mvc.perform(post("/internal/session_api_keys")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"parent_key_value\":\"" + parent + "\",\"ttl_seconds\":120,\"name\":\"agent-session-test\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.id").isNumber())
           .andExpect(jsonPath("$.key_value").isString())
           .andExpect(jsonPath("$.expires_at").isString())
           .andExpect(jsonPath("$.parent_api_key_id").isNumber())
           .andReturn();

        Map<?, ?> body = mapper.readValue(minted.getResponse().getContentAsString(), Map.class);
        int childId = ((Number) body.get("id")).intValue();

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
    }

    @Test
    void ttlAboveCapIsRejected() throws Exception {
        String parent = jdbc.queryForObject(
            "SELECT key_value FROM api_keys WHERE is_active = true AND parent_api_key_id IS NULL ORDER BY id LIMIT 1",
            Map.of(),
            String.class);

        mvc.perform(post("/internal/session_api_keys")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"parent_key_value\":\"" + parent + "\",\"ttl_seconds\":999999}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void mintedKeyCannotMintFurtherKeys() throws Exception {
        String parent = jdbc.queryForObject(
            "SELECT key_value FROM api_keys WHERE is_active = true AND parent_api_key_id IS NULL ORDER BY id LIMIT 1",
            Map.of(),
            String.class);

        MvcResult minted = mvc.perform(post("/internal/session_api_keys")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"parent_key_value\":\"" + parent + "\",\"ttl_seconds\":60}"))
           .andExpect(status().isOk())
           .andReturn();
        Map<?, ?> body = mapper.readValue(minted.getResponse().getContentAsString(), Map.class);
        String childValue = (String) body.get("key_value");

        mvc.perform(post("/internal/session_api_keys")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"parent_key_value\":\"" + childValue + "\",\"ttl_seconds\":60}"))
           .andExpect(status().isBadRequest());
    }
}
