package de.tum.cit.aet.logos.logoswebservice.operations;

import java.nio.charset.StandardCharsets;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.HttpHeaders;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.not;

/**
 * The CSV download of the team's request traces.
 *
 * The file is written on the application server, one row per request of the
 * window, newest first. The seed adds a consented row whose stored question
 * carries a comma and double quotes — the exact content that breaks a naive
 * cell — so the test pins down that payloads go out as compact JSON inside
 * quoted cells, and that the authorization header does not survive the trip.
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
     "/sql/seed-operations-export.sql", "/sql/seed-operations-export-csv.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-operations-export.sql", "/sql/cleanup-operations.sql",
     "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class TeamActivityExportCsvTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void itWritesOneCsvRowPerRequestNewestFirst() throws Exception {
        String body = mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"format\": \"csv\"}"))
           .andExpect(status().isOk())
           .andExpect(header().string(HttpHeaders.CONTENT_TYPE, "text/csv; charset=utf-8"))
           .andExpect(header().string(HttpHeaders.CONTENT_DISPOSITION,
               "attachment; filename=\"logos-traces-team-2001-7d.csv\""))
           .andExpect(header().string("X-Logos-Export-Total", "4"))
           .andExpect(header().string("X-Logos-Export-Truncated", "false"))
           .andExpect(header().string("X-Logos-Export-Count", "4"))
           .andReturn()
           .getResponse()
           .getContentAsString(StandardCharsets.UTF_8);

        String[] lines = body.split("\n");
        // Header first, then one row per request of the window — the four
        // rows team 2001 has, newest first.
        assertEquals("request_id,timestamp_request,timestamp_forwarding,timestamp_response,"
                + "time_at_first_token,privacy_level,model_name,provider_type,environment,"
                + "api_key_id,api_key_name,username,full_name,team_name,client_ip,status,"
                + "error_message,priority,initial_priority,priority_when_scheduled,"
                + "queue_depth_at_enqueue,queue_depth_at_schedule,queue_depth_at_arrival,"
                + "timeout_s,utilization_at_arrival,queue_wait_ms,was_cold_start,"
                + "load_duration_ms,available_vram_mb,prompt_tokens,completion_tokens,"
                + "total_tokens,cost_microcents,classification_statistics,input_payload,headers,"
                + "response_payload", lines[0]);
        assertEquals(5, lines.length);
        assertTrue(lines[1].startsWith("req-csv-045,"));
        int newest = body.indexOf("req-csv-045");
        int second = body.indexOf("req-ddd-444");
        int third = body.indexOf("req-ccc-333");
        int oldest = body.indexOf("req-aaa-111");
        assertTrue(newest < second && second < third && third < oldest,
                   "rows must come back newest first: " + newest + " " + second + " " + third + " " + oldest);

        // A billing-only row stored no content: the row is present, the
        // content columns at the end of it are simply empty.
        String billingLine = lines[2];
        assertTrue(billingLine.startsWith("req-ddd-444,"));
        assertTrue(billingLine.endsWith(",,,"));
    }

    @Test
    void theCsvQuotesAndEscapesStructuredCells() throws Exception {
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{\"format\": \"csv\"}"))
           .andExpect(status().isOk())
           // The stored question "Hello, \"Logos\" - are we done?" comes out
           // as compact JSON inside a quoted cell: the JSON string escapes
           // stay, the cell's own quotes come out doubled — one row per
           // request must stay one row in the file.
           .andExpect(content().string(containsString("\\\"\"Logos\\\"\"")))
           .andExpect(content().string(containsString("\"\"content-type\"\":\"\"application/json\"\"")))
           .andExpect(content().string(not(containsString("authorization"))));
    }
}
