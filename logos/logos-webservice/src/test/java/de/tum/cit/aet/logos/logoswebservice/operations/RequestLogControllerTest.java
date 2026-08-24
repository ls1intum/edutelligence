package de.tum.cit.aet.logos.logoswebservice.operations;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import static org.mockito.Mockito.when;
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
           .andExpect(jsonPath("$.offset").value(0))
           .andExpect(jsonPath("$.has_more").value(false));
    }

    @Test
    void latestRequests_pagesIntoOlderRowsWithoutRepeatingThem() throws Exception {
        // One row per page: page 1 must hold the newest and announce more,
        // page 2 the next one and announce the end. This is what "load older"
        // in the statistics feed walks through.
        mvc.perform(post("/logosdb/latest_requests")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"limit\": 1, \"offset\": 0}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests.length()").value(1))
           .andExpect(jsonPath("$.requests[0].request_id").value("req-bbb-222"))
           .andExpect(jsonPath("$.total").value(2))
           .andExpect(jsonPath("$.has_more").value(true));

        mvc.perform(post("/logosdb/latest_requests")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{\"limit\": 1, \"offset\": 1}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests.length()").value(1))
           .andExpect(jsonPath("$.requests[0].request_id").value("req-aaa-111"))
           .andExpect(jsonPath("$.offset").value(1))
           .andExpect(jsonPath("$.has_more").value(false));
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

    @Test
    void paginatedRequests_returnsPaginatedResult() throws Exception {
        mvc.perform(post("/logosdb/paginated_requests")
                .with(TestJwt.testUser())
                .contentType("application/json")
                .content("{\"page\": 1, \"per_page\": 10}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests").isArray())
           .andExpect(jsonPath("$.total").isNumber())
           .andExpect(jsonPath("$.page").value(1))
           .andExpect(jsonPath("$.per_page").value(10))
           .andExpect(jsonPath("$.total_pages").isNumber());
    }

    @Test
    void paginatedRequests_nonAdminSeesOnlyOwnRequests() throws Exception {
        // admin-key-1 (app_admin, not logos_admin) made no requests itself —
        // the per-key filter must still apply.
        when(jwtDecoder.decode("admin-key-1")).thenReturn(TestJwt.adminJwt());

        mvc.perform(post("/logosdb/paginated_requests")
                .header("logos-key", "admin-key-1")
                .contentType("application/json")
                .content("{\"page\": 1, \"per_page\": 10}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.total").value(0))
           .andExpect(jsonPath("$.requests").isEmpty());
    }

    @Test
    void paginatedRequests_logosAdminSeesRequestsAcrossAllKeys() throws Exception {
        // logos-admin-key has no log entries of its own. On production all
        // traffic comes from other keys, so without the all-keys view the
        // admin's request history (and its pagination) stayed empty.
        when(jwtDecoder.decode("logos-admin-key")).thenReturn(TestJwt.logosAdminJwt());

        mvc.perform(post("/logosdb/paginated_requests")
                .header("logos-key", "logos-admin-key")
                .contentType("application/json")
                .content("{\"page\": 1, \"per_page\": 10}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.total").value(2))
           .andExpect(jsonPath("$.requests.length()").value(2))
           .andExpect(jsonPath("$.requests[0].request_id").value("req-bbb-222"))
           // application-key-style request: environment set, no user
           .andExpect(jsonPath("$.requests[0].username").isEmpty())
           .andExpect(jsonPath("$.requests[0].environment").value("production"))
           // developer-key request: username set, no environment
           .andExpect(jsonPath("$.requests[1].request_id").value("req-aaa-111"))
           .andExpect(jsonPath("$.requests[1].username").value("testuser"))
           .andExpect(jsonPath("$.requests[1].environment").isEmpty());
    }
}
