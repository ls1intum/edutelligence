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
class RequestLogStatsControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void requestLogStats_returnsExpectedShape() throws Exception {
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.range.start").isString())
           .andExpect(jsonPath("$.range.end").isString())
           .andExpect(jsonPath("$.bucketSeconds").isNumber())
           .andExpect(jsonPath("$.stats.totals.requests").isNumber())
           .andExpect(jsonPath("$.stats.timeSeries").isArray())
           .andExpect(jsonPath("$.stats.modelBreakdown").isArray());
    }

    @Test
    void requestLogStats_rejectsUnauthenticated() throws Exception {
        mvc.perform(post("/logosdb/request_log_stats")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }

    // ── Access ───────────────────────────────────────────────────────────────
    // Unscoped, these endpoints return the whole platform's request data — and
    // the scope narrows to any team or requester the caller names, so a non
    // admin calling them with a foreign team id would read exactly what the
    // team activity endpoint (issue #776) refuses them. The rule must hold
    // here, not only on the statistics page's router gate.

    @Test
    void requestLogStats_refusesAnAppAdmin() throws Exception {
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void requestLogStats_refusesAPlainDeveloper() throws Exception {
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void requestLogStats_refusesScopeOptionsForAPlainDeveloper() throws Exception {
        // The lists name every team and requester with traffic in range — the
        // inventory of the platform's usage, so they carry the same rule.
        mvc.perform(post("/logosdb/request_log_scope_options")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void requestLogStats_refusesScopeOptionsForAnAppAdmin() throws Exception {
        mvc.perform(post("/logosdb/request_log_scope_options")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    // ── Scope ────────────────────────────────────────────────────────────────
    // The seed holds exactly two requests: 9001 carries user 1001 / team 2001,
    // 9002 carries neither (an application key). So an unscoped call must count
    // both, and any scope must count one — which is also what proves the filter
    // reaches each aggregate rather than only the top-level count.

    @Test
    void requestLogStats_countsEveryTeamWhenUnscoped() throws Exception {
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.stats.totals.requests").value(2))
           .andExpect(jsonPath("$.stats.totals.coldStarts").value(1))
           .andExpect(jsonPath("$.stats.totals.warmStarts").value(1));
    }

    @Test
    void requestLogStats_narrowsEveryAggregateToTheTeam() throws Exception {
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"team_id\": 2001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.stats.totals.requests").value(1))
           // 9002 is the cold one and belongs to no team, so scoping must drop
           // it from the cold-start count too — not just from the total.
           .andExpect(jsonPath("$.stats.totals.coldStarts").value(0))
           .andExpect(jsonPath("$.stats.totals.warmStarts").value(1))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].requestCount").value(1))
           .andExpect(jsonPath("$.stats.statusCounts.success").value(1));
    }

    @Test
    void requestLogStats_narrowsToTheRequester() throws Exception {
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"user_id\": 1001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.stats.totals.requests").value(1));
    }

    @Test
    void requestLogStats_returnsNothingForATeamWithNoTraffic() throws Exception {
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"team_id\": 999999}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.stats.totals.requests").value(0))
           .andExpect(jsonPath("$.stats.modelBreakdown").isEmpty());
    }

    @Test
    void requestLogStats_combinesUserAndTeam() throws Exception {
        // The two narrow together rather than either one winning: user 1001 is
        // in team 2001, so pairing them keeps the request, and pairing the user
        // with a different team keeps nothing.
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"user_id\": 1001, \"team_id\": 2001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.stats.totals.requests").value(1));

        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"user_id\": 1001, \"team_id\": 999999}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.stats.totals.requests").value(0));
    }

    // ── Scope options ────────────────────────────────────────────────────────
    // What the filter dropdowns offer. The lists used to be the platform's user
    // and team inventory, most of which has never sent a request; these hold
    // only what the range actually contains.

    @Test
    void scopeOptions_listOnlyWhatSentSomething() throws Exception {
        mvc.perform(post("/logosdb/request_log_scope_options")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           // One team and one requester, out of a seed holding several of each:
           // 9002 carries neither, and every other seeded user and team has no
           // traffic at all.
           .andExpect(jsonPath("$.teams.length()").value(1))
           .andExpect(jsonPath("$.teams[0].id").value(2001))
           .andExpect(jsonPath("$.teams[0].label").value("test-team"))
           .andExpect(jsonPath("$.teams[0].requestCount").value(1))
           .andExpect(jsonPath("$.requesters.length()").value(1))
           .andExpect(jsonPath("$.requesters[0].id").value(1001))
           .andExpect(jsonPath("$.requesters[0].label").value("Test User"))
           .andExpect(jsonPath("$.requesters[0].requestCount").value(1));
    }

    @Test
    void scopeOptions_narrowRequestersToTheTeam() throws Exception {
        mvc.perform(post("/logosdb/request_log_scope_options")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"team_id\": 2001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requesters.length()").value(1))
           .andExpect(jsonPath("$.requesters[0].id").value(1001))
           // The team list itself stays whole: it is the control being used to
           // choose, so narrowing it by the current choice would leave no way
           // back to the others.
           .andExpect(jsonPath("$.teams.length()").value(1));
    }

    @Test
    void scopeOptions_offerNoRequestersForASilentTeam() throws Exception {
        mvc.perform(post("/logosdb/request_log_scope_options")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"team_id\": 999999}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requesters").isEmpty());
    }

    @Test
    void scopeOptions_excludeARangeWithNoTraffic() throws Exception {
        mvc.perform(post("/logosdb/request_log_scope_options")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"start_date\": \"2020-01-01T00:00:00Z\", \"end_date\": \"2020-01-02T00:00:00Z\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.teams").isEmpty())
           .andExpect(jsonPath("$.requesters").isEmpty());
    }

    @Test
    void scopeOptions_rejectUnauthenticated() throws Exception {
        mvc.perform(post("/logosdb/request_log_scope_options")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void requestLogStats_rejectsInvalidDateRange() throws Exception {
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"start_date\": \"2025-06-01T00:00:00Z\", \"end_date\": \"2025-01-01T00:00:00Z\"}"))
           .andExpect(status().isBadRequest());
    }
}
