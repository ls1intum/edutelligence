package de.tum.cit.aet.logos.logoswebservice.operations;

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
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;

/**
 * The unauthenticated public statistics page and the team opt-in that feeds
 * it. The seed carries two successful requests — 9001 on team 2001, 9002
 * teamless — and no team has opted in, so the page is empty until a test flips
 * the flag: the default state is "nothing to show", not "everything is
 * public".
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
class PublicStatsControllerTest {

    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;
    @MockitoBean JwtDecoder jwtDecoder;

    private void optInTeam(int teamId) {
        jdbc.update("UPDATE teams SET share_public_stats = TRUE WHERE id = ?", teamId);
    }

    // ── The page itself ──────────────────────────────────────────────────────

    @Test
    void publicStatsAnswersAnonymousCallers() throws Exception {
        mvc.perform(get("/stats"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.range.start").isString())
           .andExpect(jsonPath("$.range.end").isString())
           .andExpect(jsonPath("$.totals.requests").isNumber())
           .andExpect(jsonPath("$.totals.totalTokens").isNumber())
           .andExpect(jsonPath("$.models").isArray())
           .andExpect(jsonPath("$.timeSeries").isArray())
           .andExpect(jsonPath("$.timeSeries[0].timestamp").isNumber())
           .andExpect(jsonPath("$.timeSeries[0].requests").isNumber());
    }

    @Test
    void publicStatsShowsNothingUntilATeamOptedIn() throws Exception {
        // Both seeded requests are successful, but no team has opted in —
        // including the teamless one, which no flag can ever reach.
        mvc.perform(get("/stats"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.totals.requests").value(0))
           .andExpect(jsonPath("$.models").isEmpty());

        optInTeam(2001);
        mvc.perform(get("/stats"))
           .andExpect(status().isOk())
           // 9001 (team 2001, success) counts; 9002 (teamless) still does not.
           .andExpect(jsonPath("$.totals.requests").value(1))
           .andExpect(jsonPath("$.models.length()").value(1))
           .andExpect(jsonPath("$.models[0].modelName").value("gpt-4"));
    }

    // ── Success-only, opt-in-team-set filtering ──────────────────────────────
    // The rows below carry fixed dates in February 2026 and are queried with
    // the matching explicit window, so neither the seed's now()-dated rows nor
    // the wall clock at test time can move an assertion.

    @Test
    void publicStatsCountsOnlySuccessfulRequestsOfOptedInTeams() throws Exception {
        optInTeam(2001);
        // 9060/9061: failures on the opted-in team — the page is a showcase,
        // so neither status may surface. 9062: the one counted request.
        // 9063: a success on a team that never opted in. 9064: a teamless
        // application-key success.
        jdbc.update("""
            INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                                   timestamp_request, timestamp_forwarding, timestamp_response,
                                   was_cold_start, user_id, team_id)
            VALUES (9060, 'req-pub-060', 3001, 5001, 6001, 'error',
                    TIMESTAMPTZ '2026-02-03 12:00:00+00', TIMESTAMPTZ '2026-02-03 12:00:10+00',
                    TIMESTAMPTZ '2026-02-03 12:01:00+00', false, 1001, 2001),
                   (9061, 'req-pub-061', 3001, 5001, 6001, 'timeout',
                    TIMESTAMPTZ '2026-02-03 12:05:00+00', TIMESTAMPTZ '2026-02-03 12:05:10+00',
                    TIMESTAMPTZ '2026-02-03 12:06:00+00', false, 1001, 2001),
                   (9062, 'req-pub-062', 3001, 5002, 6001, 'success',
                    TIMESTAMPTZ '2026-02-03 12:10:00+00', TIMESTAMPTZ '2026-02-03 12:10:10+00',
                    TIMESTAMPTZ '2026-02-03 12:11:00+00', false, 1001, 2001),
                   (9063, 'req-pub-063', 3001, 5002, 6001, 'success',
                    TIMESTAMPTZ '2026-02-03 12:15:00+00', TIMESTAMPTZ '2026-02-03 12:15:10+00',
                    TIMESTAMPTZ '2026-02-03 12:16:00+00', false, 1006, 2002),
                   (9064, 'req-pub-064', 3002, 5001, 6001, 'success',
                    TIMESTAMPTZ '2026-02-03 12:20:00+00', TIMESTAMPTZ '2026-02-03 12:20:10+00',
                    TIMESTAMPTZ '2026-02-03 12:21:00+00', true, NULL, NULL)
            """);
        mvc.perform(get("/stats")
                .param("start_date", "2026-02-01T00:00:00Z")
                .param("end_date", "2026-02-05T00:00:00Z"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.range.start").value("2026-02-01T00:00:00Z"))
           .andExpect(jsonPath("$.totals.requests").value(1))
           .andExpect(jsonPath("$.models.length()").value(1))
           .andExpect(jsonPath("$.models[0].modelName").value("gpt-3.5"))
           .andExpect(jsonPath("$.models[0].requestCount").value(1))
           // One of the five days of the window carried traffic; the window
           // is end-inclusive like the aggregate queries, so Feb 5 gets its
           // own zero bucket, and the quiet days are zero-filled, not absent.
           .andExpect(jsonPath("$.timeSeries.length()").value(5))
           .andExpect(jsonPath("$.timeSeries[0].requests").value(0))
           .andExpect(jsonPath("$.timeSeries[1].requests").value(0))
           .andExpect(jsonPath("$.timeSeries[2].timestamp").value(1770076800000L))
           .andExpect(jsonPath("$.timeSeries[2].requests").value(1))
           .andExpect(jsonPath("$.timeSeries[3].requests").value(0))
           // The end date's own bucket is present and zero — a request exactly
           // at end_date is counted by the aggregates, so its day must exist.
           .andExpect(jsonPath("$.timeSeries[4].requests").value(0));
    }

    @Test
    void publicStatsSumsOnlyTheTokensOfCountedRequests() throws Exception {
        optInTeam(2001);
        jdbc.update("INSERT INTO token_types (id, name) VALUES (91010, 'total_tokens') ON CONFLICT DO NOTHING");
        jdbc.update("""
            INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                                   timestamp_request, timestamp_forwarding, timestamp_response,
                                   was_cold_start, user_id, team_id)
            VALUES (9060, 'req-pub-060', 3001, 5001, 6001, 'error',
                    TIMESTAMPTZ '2026-02-03 12:00:00+00', TIMESTAMPTZ '2026-02-03 12:00:10+00',
                    TIMESTAMPTZ '2026-02-03 12:01:00+00', false, 1001, 2001),
                   (9062, 'req-pub-062', 3001, 5002, 6001, 'success',
                    TIMESTAMPTZ '2026-02-03 12:10:00+00', TIMESTAMPTZ '2026-02-03 12:10:10+00',
                    TIMESTAMPTZ '2026-02-03 12:11:00+00', false, 1001, 2001)
            """);
        jdbc.update("""
            INSERT INTO usage_tokens (id, type_id, log_entry_id, token_count)
            VALUES (93101, (SELECT id FROM token_types WHERE name = 'total_tokens'), 9060, 777),
                   (93102, (SELECT id FROM token_types WHERE name = 'total_tokens'), 9062, 150),
                   (93103, (SELECT id FROM token_types WHERE name = 'total_tokens'), 9001, 55)
            """);
        // 9060 is a failure and 9001 sits outside the window — both carry
        // total_tokens rows that the sum must skip.
        mvc.perform(get("/stats")
                .param("start_date", "2026-02-01T00:00:00Z")
                .param("end_date", "2026-02-05T00:00:00Z"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.totals.requests").value(1))
           .andExpect(jsonPath("$.totals.totalTokens").value(150));
    }

    // ── Window rules ─────────────────────────────────────────────────────────

    @Test
    void publicStatsRefusesAWindowWiderThanNinetyDays() throws Exception {
        mvc.perform(get("/stats")
                .param("start_date", "2026-01-01T00:00:00Z")
                .param("end_date", "2026-04-02T00:00:00Z"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").isString());
        // The boundary itself stays open: exactly ninety days is served.
        mvc.perform(get("/stats")
                .param("start_date", "2026-01-01T00:00:00Z")
                .param("end_date", "2026-04-01T00:00:00Z"))
           .andExpect(status().isOk());
    }

    @Test
    void publicStatsRefusesAStartAfterTheEnd() throws Exception {
        mvc.perform(get("/stats")
                .param("start_date", "2026-02-03T00:00:00Z")
                .param("end_date", "2026-02-01T00:00:00Z"))
           .andExpect(status().isBadRequest())
           .andExpect(jsonPath("$.error").isString());
    }

    // ── The team opt-in ──────────────────────────────────────────────────────

    @Test
    void aLogosAdminCanToggleTheFlagAndSeesItInTheTeamDetail() throws Exception {
        mvc.perform(patch("/teams/2001/public-stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"share_public_stats\": true}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.id").value(2001))
           .andExpect(jsonPath("$.name").value("test-team"));

        mvc.perform(get("/teams/2001/members")
                .with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.team.share_public_stats").value(true));
    }

    @Test
    void aTeamOwnerCanToggleTheFlag() throws Exception {
        mvc.perform(patch("/teams/2001/public-stats")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"share_public_stats\": true}"))
           .andExpect(status().isOk());
    }

    @Test
    void anAppAdminWithoutOwnershipIsRefused() throws Exception {
        // 2002's only member is a plain developer, so the app admin is
        // neither owner nor member of it.
        mvc.perform(patch("/teams/2002/public-stats")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"share_public_stats\": true}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void aPlainDeveloperIsRefused() throws Exception {
        mvc.perform(patch("/teams/2001/public-stats")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"share_public_stats\": true}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void theToggleRefusesUnauthenticatedCalls() throws Exception {
        mvc.perform(patch("/teams/2001/public-stats")
                .contentType("application/json")
                .content("{\"share_public_stats\": true}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void aMissingFlagValueIsRejected() throws Exception {
        mvc.perform(patch("/teams/2001/public-stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void anUnknownTeamIsNotFound() throws Exception {
        mvc.perform(patch("/teams/999999/public-stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"share_public_stats\": true}"))
           .andExpect(status().isNotFound());
    }

    @Test
    void switchingTheFlagOffRemovesTheTeamFromThePageAgain() throws Exception {
        mvc.perform(patch("/teams/2001/public-stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"share_public_stats\": true}"))
           .andExpect(status().isOk());
        mvc.perform(get("/stats"))
           .andExpect(jsonPath("$.totals.requests").value(1));

        mvc.perform(patch("/teams/2001/public-stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"share_public_stats\": false}"))
           .andExpect(status().isOk());
        mvc.perform(get("/stats"))
           .andExpect(jsonPath("$.totals.requests").value(0));
    }
}
