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
    @Autowired JdbcTemplate jdbc;
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
    // team activity endpoint  refuses them. The rule must hold
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

    // Cold and warm starts are a property of local lanes: the KPI
    // card shows the cold-start share of "local starts", so a cloud request
    // must not land in either count — not as a warm start, and not even when
    // its row carries was_cold_start = true. The rows are added through
    // JdbcTemplate in the test body instead of a method-level @Sql: a method
    // @Sql would replace the class-level seeds for this method, and the
    // class-level cleanup still removes what this test adds (9010/9011 are in
    // cleanup-operations.sql, the provider goes with the table-wide provider
    // cleanup).
    @Test
    void requestLogStats_countsColdAndWarmStartsOnLocalRequestsOnly() throws Exception {
        jdbc.update("""
            INSERT INTO providers (id, name, base_url, provider_type, privacy_level, auth_name, auth_format)
            VALUES (6002, 'cloud-provider', 'https://api.cloud.example.com', 'cloud',
                    'CLOUD_IN_EU_BY_EU_PROVIDER', 'Authorization', 'Bearer {}')
            """);
        jdbc.update("""
            INSERT INTO log_entry (id, request_id, api_key_id, model_id, provider_id, result_status,
                                   timestamp_request, timestamp_forwarding, time_at_first_token, timestamp_response,
                                   was_cold_start, queue_depth_at_enqueue, user_id, team_id, environment)
            VALUES (9010, 'req-ccc-333', 3001, 5001, 6002, 'success',
                    NOW() - INTERVAL '2 minutes', NOW() - INTERVAL '90 seconds',
                    NOW() - INTERVAL '80 seconds', NOW() - INTERVAL '70 seconds',
                    false, 0, NULL, NULL, NULL),
                   (9011, 'req-ddd-444', 3001, 5001, 6002, 'success',
                    NOW() - INTERVAL '2 minutes', NOW() - INTERVAL '90 seconds',
                    NOW() - INTERVAL '80 seconds', NOW() - INTERVAL '70 seconds',
                    true, 0, NULL, NULL, NULL)
            """);
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.stats.totals.requests").value(4))
           .andExpect(jsonPath("$.stats.totals.cloudRequests").value(2))
           .andExpect(jsonPath("$.stats.totals.localRequests").value(2))
           // Without the local-only rule this read 2 cold / 3 warm: the cloud
           // requests padded the "local starts" denominator the card shows.
           .andExpect(jsonPath("$.stats.totals.coldStarts").value(1))
           .andExpect(jsonPath("$.stats.totals.warmStarts").value(1))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].requestCount").value(4))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].coldStarts").value(1))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].warmStarts").value(1));
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
           .andExpect(jsonPath("$.requesters[0].requestCount").value(1))
           // Providers that actually carried traffic in the range, for the
           // global provider filter on the statistics page.
           .andExpect(jsonPath("$.providers").isArray())
           .andExpect(jsonPath("$.providers.length()").value(org.hamcrest.Matchers.greaterThanOrEqualTo(1)));
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

    // ── Deleted models ───────────────────────────────────────────────────────
    // Deleting a model must not drop its usage from the per-model views: the
    // rows lose their model_id but keep the name the delete captured, and the
    // entry is flagged deleted for the UI. The seed's two requests (9001/9002)
    // both sit on 5001 'gpt-4'.

    @Test
    void requestLogStats_keepsDeletedModelUsageUnderItsName() throws Exception {
        mvc.perform(post("/logosdb/delete_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk());

        // The seed's only usage is the two requests on 5001, so after the
        // delete the breakdown holds exactly one entry: the orphan, still
        // named. (Index-based on purpose: JSONPath filter expressions do not
        // match string values here, and the order is requestCount DESC.)
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.stats.modelBreakdown.length()").value(1))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].modelId").isEmpty())
           .andExpect(jsonPath("$.stats.modelBreakdown[0].modelName").value("gpt-4"))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].modelDeleted").value(true))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].requestCount").value(2))
           .andExpect(jsonPath("$.stats.modelTimeSeries").isNotEmpty())
           // The totals never keyed on the model, so the delete changes nothing there.
           .andExpect(jsonPath("$.stats.totals.requests").value(2));
    }

    @Test
    void requestLogStats_showsOrphanUsageUnderItsCapturedName() throws Exception {
        // Body inserts follow the 9010/9011 pattern: the class-level cleanup
        // removes them (9030/9031 are in cleanup-operations.sql).
        jdbc.update("""
            INSERT INTO log_entry (id, request_id, api_key_id, model_id, model_name, provider_id, result_status,
                                   timestamp_request, timestamp_forwarding, timestamp_response,
                                   was_cold_start, user_id, team_id)
            VALUES (9030, 'req-eee-555', 3001, NULL, 'retired-model', 6001, 'success',
                    NOW() - INTERVAL '7 minutes', NOW() - INTERVAL '6 minutes', NOW() - INTERVAL '5 minutes',
                    false, NULL, NULL),
                   (9031, 'req-fff-666', 3001, NULL, NULL, 6001, 'success',
                    NOW() - INTERVAL '7 minutes', NOW() - INTERVAL '6 minutes', NOW() - INTERVAL '5 minutes',
                    false, NULL, NULL)
            """);

        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           // Order is requestCount DESC: the live gpt-4 pair first, then the
           // single orphan row under its captured name.
           .andExpect(jsonPath("$.stats.modelBreakdown.length()").value(2))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].modelName").value("gpt-4"))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].requestCount").value(2))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].modelDeleted").value(false))
           .andExpect(jsonPath("$.stats.modelBreakdown[1].modelId").isEmpty())
           .andExpect(jsonPath("$.stats.modelBreakdown[1].modelName").value("retired-model"))
           .andExpect(jsonPath("$.stats.modelBreakdown[1].modelDeleted").value(true))
           .andExpect(jsonPath("$.stats.modelBreakdown[1].requestCount").value(1))
           // 9031 carries neither an id nor a name: a request that never
           // resolved to a model, still outside the per-model views as before,
           // while the totals count it.
           .andExpect(jsonPath("$.stats.totals.requests").value(4));
    }

    @Test
    void deleteModel_freesTheNameForAReplacementModel() throws Exception {
        // The issue's workflow: delete A, then bring the name back as a new
        // model. Nothing the delete leaves behind may collide with that.
        mvc.perform(post("/logosdb/delete_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk());

        mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"gpt-4\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Created Model"));

        // The old usage stays under the old name as the deleted entry, not
        // merged into the new model that now carries the same name: the new
        // model has no usage of its own, so the breakdown is still just the
        // orphan - and it does not carry the new model's id.
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.stats.modelBreakdown.length()").value(1))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].modelId").isEmpty())
           .andExpect(jsonPath("$.stats.modelBreakdown[0].modelName").value("gpt-4"))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].modelDeleted").value(true))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].requestCount").value(2));
    }

    @Test
    void deleteModel_freesTheNameForAnAliasOnAnotherModel() throws Exception {
        mvc.perform(post("/logosdb/delete_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"id\":5001}"))
           .andExpect(status().isOk());

        mvc.perform(post("/logosdb/add_model")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"name\":\"replacement-model\",\"aliases\":[\"gpt-4\"]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.result").value("Created Model"));

        // The old usage is still there under the retired name, not merged into
        // the successor that picked the name up as an alias: still one orphan
        // entry without a model id.
        mvc.perform(post("/logosdb/request_log_stats")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.stats.modelBreakdown.length()").value(1))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].modelId").isEmpty())
           .andExpect(jsonPath("$.stats.modelBreakdown[0].modelName").value("gpt-4"))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].modelDeleted").value(true))
           .andExpect(jsonPath("$.stats.modelBreakdown[0].requestCount").value(2));
    }
}
