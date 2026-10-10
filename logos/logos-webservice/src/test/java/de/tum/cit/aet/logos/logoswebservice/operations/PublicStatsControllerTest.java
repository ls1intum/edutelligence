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
import org.springframework.test.context.jdbc.SqlMergeMode;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;

/**
 * /public/stats is the aggregate picture of opted-in teams for people who
 * have not signed in. The fixtures mix successes with an error and a
 * timeout that share the key, team and provider of successful rows — the
 * asserted totals are what you get when only the successes count. Team
 * 2002 stays off the public page so its traffic must not leak into any
 * aggregate.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    // No scheduled rollup pass: the seed reads usage from log_entry and must
    // not have its rows rolled up halfway through a test.
    "logos.stats.rollup.refresh-cron=-",
    "logos.auth.roles.logos-admin=itg-admin",
    "logos.auth.roles.app-admin=chair-member",
    "logos.auth.sync-debounce-minutes=5"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class PublicStatsControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    @Sql(scripts = "/sql/seed-public-stats.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    @Sql(scripts = "/sql/cleanup-public-stats.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    void unauthenticatedClientGetsSuccessOnlyAggregatesForOptedInTeams() throws Exception {
        // Only team 2001 is opted in. Successes on that team: 9101/9102/9107
        // (developer key). 9103 (error) and 9104 (timeout) would move every
        // total below if counted. Team 2002's two application-key successes
        // stay out of every figure — including key-type and lane splits —
        // so totals match what the page shows.
        mvc.perform(get("/public/stats"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.days").value("30"))
           .andExpect(jsonPath("$.students").value(1))
           .andExpect(jsonPath("$.teams").value(1))
           .andExpect(jsonPath("$.successful_requests").value(3))
           .andExpect(jsonPath("$.average_requests_per_user").value(3.0))
           .andExpect(jsonPath("$.requests_per_team.length()").value(1))
           .andExpect(jsonPath("$.requests_per_team[0].team_id").value(2001))
           .andExpect(jsonPath("$.requests_per_team[0].team_name").value("test-team"))
           .andExpect(jsonPath("$.requests_per_team[0].requests").value(3))
           .andExpect(jsonPath("$.requests_by_key_type.developer").value(3))
           .andExpect(jsonPath("$.requests_by_key_type.application").value(0))
           .andExpect(jsonPath("$.requests_by_key_type.service").value(0))
           .andExpect(jsonPath("$.requests_by_key_type.unknown").value(0))
           .andExpect(jsonPath("$.local_cloud_requests.local").value(1))
           .andExpect(jsonPath("$.local_cloud_requests.cloud").value(2))
           .andExpect(jsonPath("$.local_cloud_requests.unknown").value(0));
    }

    @Test
    @Sql(scripts = "/sql/seed-public-stats.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    @Sql(scripts = "/sql/cleanup-public-stats.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    void usageFiguresCountSuccessfulTokensOnOptedInTeamsOnly() throws Exception {
        // Successes 9101 (100, cloud), 9102 (50, local) and 9107 (30, cloud)
        // are in the window. The error row's 1000 tokens and team 2002's
        // traffic must not show up anywhere.
        mvc.perform(get("/public/stats"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.tokens").value(180))
           .andExpect(jsonPath("$.local_cloud_tokens.local").value(50))
           .andExpect(jsonPath("$.local_cloud_tokens.cloud").value(130))
           .andExpect(jsonPath("$.active_persons").value(1))
           .andExpect(jsonPath("$.active_teams").value(1))
           .andExpect(jsonPath("$.categories.length()").value(1))
           .andExpect(jsonPath("$.categories[0].category").value("Research"))
           .andExpect(jsonPath("$.categories[0].teams").value(1))
           .andExpect(jsonPath("$.categories[0].requests").value(3))
           .andExpect(jsonPath("$.categories[0].tokens").value(180))
           .andExpect(jsonPath("$.models.all.length()").value(1))
           .andExpect(jsonPath("$.models.all[0].model").value("gpt-4"))
           .andExpect(jsonPath("$.models.all[0].requests").value(3))
           .andExpect(jsonPath("$.models.local[0].requests").value(1))
           .andExpect(jsonPath("$.models.cloud[0].requests").value(2))
           // One active person is below the publishing threshold.
           .andExpect(jsonPath("$.usage_per_person.count").value(1))
           .andExpect(jsonPath("$.usage_per_person.suppressed").value(true))
           .andExpect(jsonPath("$.usage_per_person.requests").doesNotExist())
           .andExpect(jsonPath("$.usage_per_team.count").value(1))
           .andExpect(jsonPath("$.usage_per_team.requests.median").value(3.0))
           .andExpect(jsonPath("$.usage_per_team.tokens.median").value(180.0))
           // The monthly series starts with the month of the 40-day-old success.
           .andExpect(jsonPath("$.monthly[0].requests").value(1))
           .andExpect(jsonPath("$.monthly[0].tokens").value(7))
           .andExpect(jsonPath("$.monthly[0].persons").value(1))
           .andExpect(jsonPath("$.monthly[0].students").value(1))
           // Everything else is in the current, still incomplete week.
           .andExpect(jsonPath("$.regular_activity.persons_any").value(0))
           .andExpect(jsonPath("$.agent.sessions").value(0));
    }

    @Test
    @Sql(scripts = "/sql/seed-public-stats.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    @Sql(scripts = "/sql/cleanup-public-stats.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    void adminsSetAndClearAPublicCategory() throws Exception {
        mvc.perform(patch("/teams/2002")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"public_category\":\"  Teaching  \"}"))
           .andExpect(status().isOk());

        mvc.perform(get("/teams/public-categories").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(2))
           .andExpect(jsonPath("$[0]").value("Research"))
           .andExpect(jsonPath("$[1]").value("Teaching"));

        mvc.perform(patch("/teams/2002")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"public_category\":\"\"}"))
           .andExpect(status().isOk());

        mvc.perform(get("/teams/public-categories").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.length()").value(1));

        mvc.perform(patch("/teams/2002")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"public_category\":\"" + "x".repeat(65) + "\"}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void developersCannotListPublicCategories() throws Exception {
        mvc.perform(get("/teams/public-categories").with(TestJwt.testUser()))
           .andExpect(status().isForbidden());
    }

    @Test
    @Sql(scripts = "/sql/seed-public-stats.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    @Sql(scripts = "/sql/cleanup-public-stats.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    void daysWindowExcludesOlderSuccesses() throws Exception {
        // 9110 is a 2001 success from 40 days ago: outside the default 30d
        // and the 7d window, inside days=90 / days=all.
        mvc.perform(get("/public/stats").param("days", "7"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.days").value("7"))
           .andExpect(jsonPath("$.successful_requests").value(3))
           .andExpect(jsonPath("$.students").value(1))
           .andExpect(jsonPath("$.requests_per_team[0].requests").value(3));

        mvc.perform(get("/public/stats").param("days", "90"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.days").value("90"))
           .andExpect(jsonPath("$.successful_requests").value(4))
           .andExpect(jsonPath("$.requests_per_team[0].requests").value(4));

        mvc.perform(get("/public/stats").param("days", "all"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.days").value("all"))
           .andExpect(jsonPath("$.successful_requests").value(4))
           .andExpect(jsonPath("$.average_requests_per_user").value(4.0))
           .andExpect(jsonPath("$.requests_per_team[0].requests").value(4));
    }

    @Test
    @Sql(scripts = {"/sql/seed-public-stats.sql", "/sql/seed-public-stats-extra.sql"},
         executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    @Sql(scripts = {"/sql/cleanup-public-stats-extra.sql", "/sql/cleanup-public-stats.sql"},
         executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    void agentFiguresPublishOptedInTeamsOnlyAndCountPeopleNotAutomation() throws Exception {
        // 7 days: the published team's human session (9821) and the
        // platform-written sessions — trigger (9822), the runner's re-queued
        // attempt (9826) and the workflow-analysis session (9827) — count;
        // 9823 (private team), 9824 (no repository) and 9825 (an hour before
        // the window start) do not. The three automation identities add
        // sessions but none of them is a person, so users stays at 1.
        mvc.perform(get("/public/stats").param("days", "7"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.agent.sessions").value(4))
           .andExpect(jsonPath("$.agent.users").value(1))
           .andExpect(jsonPath("$.agent.succeeded").value(1))
           .andExpect(jsonPath("$.agent.pull_requests").value(1));

        // All time keeps the older published session; the private team's and
        // the repository-less session stay out.
        mvc.perform(get("/public/stats").param("days", "all"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.agent.sessions").value(5))
           .andExpect(jsonPath("$.agent.users").value(1));
    }

    @Test
    @Sql(scripts = {"/sql/seed-public-stats.sql", "/sql/seed-public-stats-extra.sql"},
         executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    @Sql(scripts = {"/sql/cleanup-public-stats-extra.sql", "/sql/cleanup-public-stats.sql"},
         executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    void headlineAndUsageFiguresAgreeAtTheWindowBoundary() throws Exception {
        // 9111 was requested just before the 7-day boundary and forwarded
        // after it. Both the headline total and the usage figures range on the
        // request timestamp, so neither counts it; with days=30 both do.
        mvc.perform(get("/public/stats").param("days", "7"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.successful_requests").value(3))
           .andExpect(jsonPath("$.categories[0].requests").value(3))
           .andExpect(jsonPath("$.models.all[0].requests").value(3))
           .andExpect(jsonPath("$.tokens").value(180));

        mvc.perform(get("/public/stats").param("days", "30"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.successful_requests").value(4))
           .andExpect(jsonPath("$.categories[0].requests").value(4))
           .andExpect(jsonPath("$.models.all[0].requests").value(4))
           .andExpect(jsonPath("$.tokens").value(191));
    }

    @Test
    void rejectsUnknownDaysValue() throws Exception {
        mvc.perform(get("/public/stats").param("days", "14"))
           .andExpect(status().isBadRequest());
    }

    @Test
    @Sql(scripts = "/sql/seed-public-stats.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    @Sql(scripts = "/sql/cleanup-public-stats.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    void aValidJwtGetsTheSameView() throws Exception {
        mvc.perform(get("/public/stats").with(TestJwt.testUser()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.students").value(1))
           .andExpect(jsonPath("$.teams").value(1));
    }

    @Test
    void aPlatformWithoutOptedInTeamsReportsZeroes() throws Exception {
        // Identity seed leaves both teams off the public page by default.
        mvc.perform(get("/public/stats"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.days").value("30"))
           .andExpect(jsonPath("$.students").value(0))
           .andExpect(jsonPath("$.teams").value(0))
           .andExpect(jsonPath("$.successful_requests").value(0))
           .andExpect(jsonPath("$.average_requests_per_user").value(0.0))
           .andExpect(jsonPath("$.requests_per_team").isEmpty())
           .andExpect(jsonPath("$.requests_by_key_type.developer").value(0))
           .andExpect(jsonPath("$.requests_by_key_type.application").value(0))
           .andExpect(jsonPath("$.requests_by_key_type.service").value(0))
           .andExpect(jsonPath("$.requests_by_key_type.unknown").value(0))
           .andExpect(jsonPath("$.local_cloud_requests.local").value(0))
           .andExpect(jsonPath("$.local_cloud_requests.cloud").value(0))
           .andExpect(jsonPath("$.local_cloud_requests.unknown").value(0));
    }

    @Test
    @Sql(scripts = "/sql/seed-public-stats.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    @Sql(scripts = "/sql/cleanup-public-stats.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    void optingATeamInPublishesItsNameAndTraffic() throws Exception {
        mvc.perform(patch("/teams/2002")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"show_on_public_stats\":true}"))
           .andExpect(status().isOk());

        // Both teams now publish: 2001 still leads with 3 recent successes;
        // 2002's two application-key successes appear and raise the headline
        // total to 5. The per-student average must stay at 3 — those two
        // application-key rows have no user and must not inflate the cohort
        // numerator (3 student requests / 1 active student, not 5 / 1).
        mvc.perform(get("/public/stats"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.teams").value(2))
           .andExpect(jsonPath("$.students").value(1))
           .andExpect(jsonPath("$.successful_requests").value(5))
           .andExpect(jsonPath("$.average_requests_per_user").value(3.0))
           .andExpect(jsonPath("$.requests_per_team.length()").value(2))
           .andExpect(jsonPath("$.requests_per_team[0].team_id").value(2001))
           .andExpect(jsonPath("$.requests_per_team[1].team_id").value(2002))
           .andExpect(jsonPath("$.requests_per_team[1].team_name").value("kc-team"))
           .andExpect(jsonPath("$.requests_by_key_type.application").value(2))
           .andExpect(jsonPath("$.local_cloud_requests.cloud").value(4));
    }

    @Test
    @Sql(scripts = "/sql/seed-public-stats-orphan.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    @Sql(scripts = "/sql/cleanup-public-stats-orphan.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    void orphanKeyAndProviderSuccessCountsUnderUnknown() throws Exception {
        // 9108 succeeded on published team 2001 and its API key and its
        // provider were deleted afterwards (both ids SET NULL). The headline
        // and both splits keep counting it; each split carries it under its
        // unknown bucket, so both still sum to successful_requests. With an
        // inner join on the key or the provider the row would drop out of a
        // split and the split would no longer agree with the headline.
        mvc.perform(get("/public/stats"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.days").value("30"))
           .andExpect(jsonPath("$.students").value(0))
           .andExpect(jsonPath("$.teams").value(1))
           .andExpect(jsonPath("$.successful_requests").value(1))
           .andExpect(jsonPath("$.average_requests_per_user").value(0.0))
           .andExpect(jsonPath("$.requests_per_team.length()").value(1))
           .andExpect(jsonPath("$.requests_per_team[0].team_id").value(2001))
           .andExpect(jsonPath("$.requests_per_team[0].requests").value(1))
           .andExpect(jsonPath("$.requests_by_key_type.developer").value(0))
           .andExpect(jsonPath("$.requests_by_key_type.application").value(0))
           .andExpect(jsonPath("$.requests_by_key_type.service").value(0))
           .andExpect(jsonPath("$.requests_by_key_type.unknown").value(1))
           .andExpect(jsonPath("$.local_cloud_requests.local").value(0))
           .andExpect(jsonPath("$.local_cloud_requests.cloud").value(0))
           .andExpect(jsonPath("$.local_cloud_requests.unknown").value(1))
           .andExpect(jsonPath("$.tokens").value(0));
    }
}
