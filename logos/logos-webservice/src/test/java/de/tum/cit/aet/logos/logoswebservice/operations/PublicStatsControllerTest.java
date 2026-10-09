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
}
