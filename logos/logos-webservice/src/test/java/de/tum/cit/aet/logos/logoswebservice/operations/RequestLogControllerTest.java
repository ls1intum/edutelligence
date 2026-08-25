package de.tum.cit.aet.logos.logoswebservice.operations;

import com.fasterxml.jackson.databind.ObjectMapper;
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
class RequestLogControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void latestRequests_returnsUpToTenRows() throws Exception {
        mvc.perform(post("/logosdb/latest_requests")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests").isArray())
           .andExpect(jsonPath("$.requests[0].request_id").value("req-bbb-222"))
           // The feed shows a page of the range, so it reports how big the range is.
           .andExpect(jsonPath("$.total").value(2))
           .andExpect(jsonPath("$.has_more").value(false))
           // Nothing left to page to, so no cursor to page with.
           .andExpect(jsonPath("$.next_cursor").isEmpty());
    }

    @Test
    void latestRequests_pagesByCursorWithoutRepeatingRows() throws Exception {
        // One row per page: page 1 holds the newest and hands out the cursor to
        // continue from, page 2 the next one and announces the end.
        String page1 = mvc.perform(post("/logosdb/latest_requests")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"limit\": 1}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests.length()").value(1))
           .andExpect(jsonPath("$.requests[0].request_id").value("req-bbb-222"))
           .andExpect(jsonPath("$.total").value(2))
           .andExpect(jsonPath("$.has_more").value(true))
           .andExpect(jsonPath("$.next_cursor.request_id").value("req-bbb-222"))
           .andReturn().getResponse().getContentAsString();

        var cursor = new ObjectMapper().readTree(page1).get("next_cursor");
        mvc.perform(post("/logosdb/latest_requests")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"limit\": 1, \"cursor_ts\": \"" + cursor.get("ts").asText()
                         + "\", \"cursor_id\": \"" + cursor.get("request_id").asText() + "\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests.length()").value(1))
           .andExpect(jsonPath("$.requests[0].request_id").value("req-aaa-111"))
           .andExpect(jsonPath("$.has_more").value(false));
    }

    @Test
    void latestRequests_filtersByTeamAndByUser() throws Exception {
        // Only req-aaa-111 carries a user and a team; req-bbb-222 came in on an
        // application key. Both filters therefore narrow to the one row, and the
        // count has to narrow with them or the header would promise more pages.
        mvc.perform(post("/logosdb/latest_requests")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"team_id\": 2001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests.length()").value(1))
           .andExpect(jsonPath("$.requests[0].request_id").value("req-aaa-111"))
           .andExpect(jsonPath("$.total").value(1))
           .andExpect(jsonPath("$.has_more").value(false));

        mvc.perform(post("/logosdb/latest_requests")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"user_id\": 1001}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests.length()").value(1))
           .andExpect(jsonPath("$.requests[0].request_id").value("req-aaa-111"))
           .andExpect(jsonPath("$.total").value(1));

        // A filter nothing matches must come back empty, not unfiltered.
        mvc.perform(post("/logosdb/latest_requests")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"user_id\": 1002}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests").isEmpty())
           .andExpect(jsonPath("$.total").value(0));
    }

    @Test
    void latestRequests_rangeOutsideAnyRequestIsEmptyButStillCounted() throws Exception {
        mvc.perform(post("/logosdb/latest_requests")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"start\": \"1990-01-01T00:00:00Z\", \"end\": \"1990-01-02T00:00:00Z\"}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests").isEmpty())
           .andExpect(jsonPath("$.total").value(0))
           .andExpect(jsonPath("$.has_more").value(false));
    }

    @Test
    void latestRequests_rejectsUnauthenticated() throws Exception {
        mvc.perform(post("/logosdb/latest_requests")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void latestRequests_rejectsNonAdmin() throws Exception {
        // The feed is system-wide and carries requester names, teams and cloud
        // cost, with no per-user scoping to fall back on.
        mvc.perform(post("/logosdb/latest_requests")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isForbidden());
    }

    @Test
    void requestLogs_returnsMatchingRows() throws Exception {
        mvc.perform(post("/logosdb/request_logs")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"request_ids\": [\"req-aaa-111\"]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests").isArray())
           .andExpect(jsonPath("$.requests[0].request_id").value("req-aaa-111"));
    }

    @Test
    void requestLogs_emptyListReturnsEmptyResult() throws Exception {
        mvc.perform(post("/logosdb/request_logs")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"request_ids\": []}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests").isArray())
           .andExpect(jsonPath("$.requests").isEmpty());
    }

    @Test
    void requestLogs_missingFieldReturns400() throws Exception {
        mvc.perform(post("/logosdb/request_logs")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isBadRequest());
    }
}
