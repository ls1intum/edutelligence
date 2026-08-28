package de.tum.cit.aet.logos.logoswebservice.operations;

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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;

/**
 * The consent-based trace export (issue #667).
 *
 * The export seed adds two rows to the shared operations seed, both in team
 * 2001 within the window: 9003 was recorded at FULL privacy and carries the
 * request and response payloads, 9004 is billing-only. Together with the
 * shared 9001 (also billing-only) they pin down the one rule that makes this
 * endpoint different from the activity view: only consented rows come back.
 * User 1002 is an app admin owning 2001; team 2002 exists and they do not own
 * it, and it has no traffic at all.
 */
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
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-operations.sql",
     "/sql/seed-operations-export.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-operations-export.sql", "/sql/cleanup-operations.sql",
     "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class TeamActivityExportControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    // ── Access ───────────────────────────────────────────────────────────────

    @Test
    void anAppAdminExportsTheTracesOfTheirOwnTeam() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.team_id").value(2001));
    }

    @Test
    void anAppAdminIsRefusedATeamTheyDoNotOwn() throws Exception {
        // The export carries request content, which is the most sensitive
        // thing the platform stores. The ownership gate is not negotiable.
        mvc.perform(post("/logosdb/teams/2002/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void aLogosAdminExportsAnyTeam() throws Exception {
        mvc.perform(post("/logosdb/teams/2002/activity/export")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.team_id").value(2002));
    }

    @Test
    void aPlainDeveloperIsRefused() throws Exception {
        // 1001 is a member of 2001, but reading the team's stored content is
        // an admin job — the role gate applies like on the activity view.
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void unauthenticatedIsRefused() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }

    // ── Content ──────────────────────────────────────────────────────────────

    @Test
    void itCarriesTheFullRequestAndResponsePayloads() throws Exception {
        // The point of the opt-in: what the requester agreed to be stored is
        // what the download contains, structured rather than as a string that
        // happens to hold JSON.
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.traces.length()").value(1))
           .andExpect(jsonPath("$.traces[0].request_id").value("req-ccc-333"))
           .andExpect(jsonPath("$.traces[0].privacy_level").value("FULL"))
           .andExpect(jsonPath("$.traces[0].input_payload.model").value("gpt-4"))
           .andExpect(jsonPath("$.traces[0].input_payload.messages[0].content").value("Hello, Logos"))
           .andExpect(jsonPath("$.traces[0].response_payload.choices[0].message.content")
                .value("Hi there!"))
           .andExpect(jsonPath("$.traces[0].headers['content-type']").value("application/json"))
           .andExpect(jsonPath("$.traces[0].client_ip").value("127.0.0.1"));
    }

    @Test
    void itNamesWhoSentTheTraceAndWithWhichKey() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.traces[0].username").value("testuser"))
           .andExpect(jsonPath("$.traces[0].full_name").value("Test User"))
           .andExpect(jsonPath("$.traces[0].api_key_name").value("dev key"))
           .andExpect(jsonPath("$.traces[0].model_name").value("gpt-4"))
           .andExpect(jsonPath("$.traces[0].provider_name").value("openai-provider"))
           .andExpect(jsonPath("$.traces[0].status").value("success"));
    }

    @Test
    void billingOnlyRequestsStayOutOfTheExport() throws Exception {
        // 9004 (billing-only, same window) and the shared 9001 (billing-only
        // default) both sit in team 2001. The count says the filter worked:
        // the export holds the single consented row and nothing else.
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.count").value(1))
           .andExpect(jsonPath("$.truncated").value(false))
           .andExpect(jsonPath("$.traces[0].request_id").value("req-ccc-333"));
    }

    @Test
    void aTeamWithoutConsentedTrafficExportsAnEmptySet() throws Exception {
        // No rows at all, but the file is still a well-formed empty set — the
        // download must not fail just because the team never opted in.
        mvc.perform(post("/logosdb/teams/2002/activity/export")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.count").value(0))
           .andExpect(jsonPath("$.truncated").value(false))
           .andExpect(jsonPath("$.traces").isEmpty());
    }

    @Test
    void theUserFilterNarrowsTheExport() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"user_id\": 1001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.count").value(1));

        // A requester who sent no consented traffic in the team narrows to
        // nothing — the team scope still applies on top, like in the activity
        // view, so this can only ever cut the set down further.
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"user_id\": 1003}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.count").value(0));
    }

    // ── Window ───────────────────────────────────────────────────────────────

    @Test
    void theWindowIsClampedJustLikeTheActivityView() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"days\": 100000}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.days").value(90));

        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"days\": 0}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.days").value(1));
    }

    @Test
    void theExportNamesTheTeamAndItsWindow() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.team_name").value("test-team"))
           .andExpect(jsonPath("$.days").value(7))
           .andExpect(jsonPath("$.since").isNotEmpty());
    }
}
