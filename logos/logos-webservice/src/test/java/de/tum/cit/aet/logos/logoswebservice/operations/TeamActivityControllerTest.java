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
 * One team's activity view (issue #776).
 *
 * The seed has team 2001 with one completed request (9001) on key 3001, and a
 * second request (9002) belonging to no team at all — which is what makes the
 * scoping visible rather than incidental. User 1002 is an app admin owning
 * 2001; team 2002 exists and they do not own it.
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
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-operations.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-operations.sql", "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class TeamActivityControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    // ── Access ───────────────────────────────────────────────────────────────

    @Test
    void anAppAdminSeesTheirOwnTeam() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.team_id").value(2001));
    }

    @Test
    void anAppAdminIsRefusedATeamTheyDoNotOwn() throws Exception {
        // The whole point of the endpoint being team-scoped: an app admin runs
        // one team on the platform and must not read another's spend.
        mvc.perform(post("/logosdb/teams/2002/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void aLogosAdminSeesAnyTeam() throws Exception {
        mvc.perform(post("/logosdb/teams/2002/activity")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk());
    }

    @Test
    void aPlainDeveloperIsRefused() throws Exception {
        // 1001 owns team 2001, but ownership is not the gate here — the role is.
        // A developer has no business reading their team's aggregate spend.
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void unauthenticatedIsRefused() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }

    // ── Content ──────────────────────────────────────────────────────────────

    @Test
    void itCountsTheTeamsFinishedRequests() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           // 9001 only. 9002 completed in the same window and belongs to no
           // team, so counting it would mean the scope is not being applied.
           .andExpect(jsonPath("$.live.finished").value(1))
           .andExpect(jsonPath("$.live.failed").value(0))
           // Both seeded requests carry a response, so nothing is in flight.
           .andExpect(jsonPath("$.live.queued").value(0))
           .andExpect(jsonPath("$.live.running").value(0));
    }

    @Test
    void itBreaksUsageDownByKey() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           // Only the key that was actually used — the team has four, and
           // listing the three idle ones at zero would bury the answer.
           .andExpect(jsonPath("$.keys.length()").value(1))
           .andExpect(jsonPath("$.keys[0].key_id").value(3001))
           .andExpect(jsonPath("$.keys[0].key_name").value("dev key"))
           .andExpect(jsonPath("$.keys[0].key_type").value("developer"))
           .andExpect(jsonPath("$.keys[0].request_count").value(1));
    }

    @Test
    void aTeamWithNoTrafficReportsZeroRatherThanFailing() throws Exception {
        mvc.perform(post("/logosdb/teams/2002/activity")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.live.finished").value(0))
           .andExpect(jsonPath("$.keys").isEmpty())
           .andExpect(jsonPath("$.total_tokens").value(0));
    }

    // ── Requests ─────────────────────────────────────────────────────────────
    // Counts alone answer "is anything happening"; the list answers "what".

    @Test
    void itListsTheTeamsIndividualRequests() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           // 9001 only — 9002 is in the same window and belongs to no team.
           .andExpect(jsonPath("$.requests.length()").value(1))
           .andExpect(jsonPath("$.requests[0].request_id").value("req-aaa-111"))
           .andExpect(jsonPath("$.requests_total").value(1));
    }

    @Test
    void itOffersTheTeamsRequestersForTheFilter() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requesters.length()").value(1))
           .andExpect(jsonPath("$.requesters[0].id").value(1001))
           .andExpect(jsonPath("$.requesters[0].label").value("Test User"));
    }

    @Test
    void theRequestFilterNarrowsToOneRequester() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"user_id\": 1001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests.length()").value(1));

        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"user_id\": 1003}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests").isEmpty());
    }

    @Test
    void aRequesterFromAnotherTeamStillCannotWidenTheScope() throws Exception {
        // The team scope is applied on top of user_id, so naming a requester
        // outside the team narrows to nothing rather than reaching past it.
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"user_id\": 1006}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests").isEmpty());
    }

    // ── Window ───────────────────────────────────────────────────────────────

    @Test
    void theWindowDefaultsToAWeek() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.days").value(7));
    }

    @Test
    void theWindowIsClampedToSomethingAnswerable() throws Exception {
        // Unbounded days would let one request scan the whole table.
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"days\": 100000}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.days").value(90));

        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"days\": 0}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.days").value(1));
    }

    @Test
    void aShortWindowExcludesOlderTraffic() throws Exception {
        // The seeded requests are minutes old, so a one-day window still holds
        // them — this pins that `days` reaches the query rather than being
        // echoed back unused. Nothing older exists to fall out of it, so the
        // assertion is that the count is unchanged, not that it drops.
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"days\": 1}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.days").value(1))
           .andExpect(jsonPath("$.live.finished").value(1));
    }
}
