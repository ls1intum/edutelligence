package de.tum.cit.aet.logos.logoswebservice.operations;

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
import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;

/**
 * A team window bigger than one export carries.
 *
 * The class shrinks the export cap to two rows and seeds eight in the window.
 * The file then holds the two newest, and the answer says so in three places
 * a caller can reach: the response headers set before the first byte, the
 * envelope in the file itself, and the consent note computed over the slice
 * the file keeps — not the window it comes from.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    "logos.auth.roles.logos-admin=itg-admin",
    "logos.auth.roles.app-admin=chair-member",
    "logos.auth.sync-debounce-minutes=5",
    "logos.team-activity.export-max-rows=2"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-operations.sql",
     "/sql/seed-operations-export.sql", "/sql/seed-operations-export-truncation.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-operations-export.sql", "/sql/cleanup-operations.sql",
     "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class TeamActivityExportTruncationTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void theWindowBiggerThanTheCapExportsTheNewestSlice() throws Exception {
        // Eight rows in the window, a file for two: the headers say how big
        // the window is, that the file is a slice, and how many rows the
        // slice holds — before the first byte is written, because after that
        // the download cannot be taken back.
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(header().string("X-Logos-Export-Total", "8"))
           .andExpect(header().string("X-Logos-Export-Truncated", "true"))
           .andExpect(header().string("X-Logos-Export-Count", "2"))
           .andExpect(header().string(HttpHeaders.CONTENT_DISPOSITION,
               "attachment; filename=\"logos-traces-team-2001-7d.json\""))
           .andExpect(header().string(HttpHeaders.CONTENT_TYPE, "application/json"))
           .andExpect(jsonPath("$.count").value(2))
           .andExpect(jsonPath("$.truncated").value(true))
           .andExpect(jsonPath("$.total_in_window").value(8))
           .andExpect(jsonPath("$.traces.length()").value(2))
           .andExpect(jsonPath("$.traces[0].request_id").value("req-trunc-040"))
           .andExpect(jsonPath("$.traces[1].request_id").value("req-trunc-041"));
    }

    @Test
    void theConsentNoteCoversTheSliceNotTheWindow() throws Exception {
        // Full logging is activated for the team, and a consented row exists
        // in the window — one row behind the cap. The file keeps the two
        // newest rows, both billing-only, and its note is about the file: a
        // note that said "the window has consented traffic" would contradict
        // the empty content columns right below it.
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.full_logging_enabled").value(true))
           .andExpect(jsonPath("$.note").value(
               containsString("No request with full logging")));
    }

    @Test
    void aWindowThatFitsIntoOneExportSaysItIsComplete() throws Exception {
        // The same cap, a team whose window is small enough: nothing is
        // truncated, and the file is the whole answer.
        mvc.perform(post("/logosdb/teams/2002/activity/export")
                .with(TestJwt.logosAdmin())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(header().string("X-Logos-Export-Total", "0"))
           .andExpect(header().string("X-Logos-Export-Truncated", "false"))
           .andExpect(jsonPath("$.truncated").value(false))
           .andExpect(jsonPath("$.total_in_window").value(0));
    }
}
