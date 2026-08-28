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
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.nullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;

/**
 * The request trace export (issue #667).
 *
 * The export seed adds two rows and one key to the shared operations seed.
 * Both rows sit in team 2001 within the window: 9003 was recorded at FULL
 * privacy and carries the request and response payloads, 9004 is
 * billing-only. Together with the shared 9001 (also billing-only) they pin
 * down what the export shows: every request of the window, with the content
 * columns filled only where the requester consented — an export must
 * describe the same slice of traffic the activity list does, not a silently
 * smaller one. The added key 3009 turns full logging on for 2001 (the shared
 * keys are all at the BILLING default), so the "activated" and the "not
 * activated" sides of the envelope hint are both covered by the seeded
 * teams: 2002 has no keys and no traffic at all.
 * User 1002 is an app admin owning 2001; team 2002 exists and they do not own
 * it.
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
    void itCarriesEveryRequestOfTheWindowNewestFirst() throws Exception {
        // The export must describe the same slice of traffic the activity
        // list shows: the two billing rows come back right next to the
        // consented one, in the same newest-first order the feed reads.
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.count").value(3))
           .andExpect(jsonPath("$.truncated").value(false))
           .andExpect(jsonPath("$.traces.length()").value(3))
           .andExpect(jsonPath("$.traces[0].request_id").value("req-ddd-444"))
           .andExpect(jsonPath("$.traces[1].request_id").value("req-ccc-333"))
           .andExpect(jsonPath("$.traces[2].request_id").value("req-aaa-111"));
    }

    @Test
    void billingRowsComeOutWithEmptyContent() throws Exception {
        // Nothing was stored for a request the requester did not consent to,
        // and the row says exactly that: present like every other request,
        // the content columns simply empty.
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.traces[0].privacy_level").value("BILLING"))
           .andExpect(jsonPath("$.traces[0].input_payload").value(nullValue()))
           .andExpect(jsonPath("$.traces[0].response_payload").value(nullValue()))
           .andExpect(jsonPath("$.traces[0].headers").value(nullValue()))
           .andExpect(jsonPath("$.traces[0].client_ip").value(nullValue()))
           .andExpect(jsonPath("$.traces[2].privacy_level").value("BILLING"))
           .andExpect(jsonPath("$.traces[2].input_payload").value(nullValue()));
    }

    @Test
    void itCarriesTheFullRequestAndResponsePayloads() throws Exception {
        // The point of the opt-in: what the requester agreed to be stored is
        // what the download contains, structured rather than as a string that
        // happens to hold JSON. The consented row sits between the two
        // billing ones, newest first.
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.traces[1].request_id").value("req-ccc-333"))
           .andExpect(jsonPath("$.traces[1].privacy_level").value("FULL"))
           .andExpect(jsonPath("$.traces[1].input_payload.model").value("gpt-4"))
           .andExpect(jsonPath("$.traces[1].input_payload.messages[0].content").value("Hello, Logos"))
           .andExpect(jsonPath("$.traces[1].response_payload.choices[0].message.content")
                .value("Hi there!"))
           .andExpect(jsonPath("$.traces[1].headers['content-type']").value("application/json"))
           .andExpect(jsonPath("$.traces[1].client_ip").value("127.0.0.1"));
    }

    @Test
    void itNamesWhoSentTheTraceAndWithWhichKey() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.traces[1].username").value("testuser"))
           .andExpect(jsonPath("$.traces[1].full_name").value("Test User"))
           .andExpect(jsonPath("$.traces[1].api_key_name").value("dev key"))
           .andExpect(jsonPath("$.traces[1].model_name").value("gpt-4"))
           .andExpect(jsonPath("$.traces[1].status").value("success"));
    }

    @Test
    void aTeamWithoutTrafficExportsAnEmptySet() throws Exception {
        // No rows at all, but the file is still a well-formed empty set — the
        // download must not fail just because the team never sent anything.
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
           .andExpect(jsonPath("$.count").value(3));

        // A requester who sent no traffic in the team narrows to nothing —
        // the team scope still applies on top, like in the activity view, so
        // this can only ever cut the set down further.
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"user_id\": 1003}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.count").value(0));
    }

    // ── The consent hint ─────────────────────────────────────────────────────

    @Test
    void theEnvelopeSaysWhetherFullLoggingIsActivated() throws Exception {
        // 2001 has the added full key, so the download can say so — and with
        // a consented row on board there is nothing to explain, so no note.
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.full_logging_enabled").value(true))
           .andExpect(jsonPath("$.note").doesNotExist());

        // 2002 has no keys at all: the note must name the reason the content
        // of the file is empty.
        mvc.perform(post("/logosdb/teams/2002/activity/export")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.full_logging_enabled").value(false))
           .andExpect(jsonPath("$.note").value(containsString("not activated")));
    }

    @Test
    void theNoteExplainsConsentedTrafficWithoutAConsentSwitch() throws Exception {
        // Full logging is on for 2001, but this requester never sent a
        // consented request: the note has to say there was no full-logging
        // traffic in the window, not that nobody consented.
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"user_id\": 1003}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.full_logging_enabled").value(true))
           .andExpect(jsonPath("$.note").value(containsString("No request with full logging")));
    }

    @Test
    void theActivityViewCarriesTheSameFlag() throws Exception {
        // The tab shows the hint before the export is even started, so the
        // flag lives on the activity payload, not only on the envelope.
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.full_logging_enabled").value(true));
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
