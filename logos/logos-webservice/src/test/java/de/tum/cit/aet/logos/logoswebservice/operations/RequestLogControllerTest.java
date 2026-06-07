package de.tum.cit.aet.logos.logoswebservice.operations;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-operations.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-operations.sql", "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class RequestLogControllerTest {

    @Autowired MockMvc mvc;

    @Test
    void latestRequests_returnsUpToTenRows() throws Exception {
        mvc.perform(post("/logosdb/latest_requests")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests").isArray())
           .andExpect(jsonPath("$.requests[0].request_id").value("req-bbb-222"));
    }

    @Test
    void latestRequests_rejectsInvalidKey() throws Exception {
        mvc.perform(post("/logosdb/latest_requests")
                .header("logos-key", "bad-key")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void requestLogs_returnsMatchingRows() throws Exception {
        mvc.perform(post("/logosdb/request_logs")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{\"request_ids\": [\"req-aaa-111\"]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests").isArray())
           .andExpect(jsonPath("$.requests[0].request_id").value("req-aaa-111"));
    }

    @Test
    void requestLogs_emptyListReturnsEmptyResult() throws Exception {
        mvc.perform(post("/logosdb/request_logs")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{\"request_ids\": []}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests").isArray())
           .andExpect(jsonPath("$.requests").isEmpty());
    }

    @Test
    void requestLogs_missingFieldReturns400() throws Exception {
        mvc.perform(post("/logosdb/request_logs")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void paginatedRequests_returnsPaginatedResult() throws Exception {
        mvc.perform(post("/logosdb/paginated_requests")
                .header("logos-key", "dev-key-1")
                .contentType("application/json")
                .content("{\"page\": 1, \"per_page\": 10}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.requests").isArray())
           .andExpect(jsonPath("$.total").isNumber())
           .andExpect(jsonPath("$.page").value(1))
           .andExpect(jsonPath("$.per_page").value(10))
           .andExpect(jsonPath("$.total_pages").isNumber());
    }
}
