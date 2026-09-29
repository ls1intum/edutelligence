package de.tum.cit.aet.logos.logoswebservice.operations;

import java.util.Collections;
import java.util.List;

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
import com.jayway.jsonpath.JsonPath;

import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import static org.hamcrest.Matchers.containsString;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
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
 * the file keeps — not the window it comes from. And the walk continues: the
 * cursor the slice hands back reaches the rows one more slice at a time,
 * until a file arrives uncapped.
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
    @SuppressWarnings("unchecked")
    void aCappedWindowContinuesSliceBySliceToTheOldestRow() throws Exception {
        // Eight rows, a file for two: the newest slice hands back the cursor
        // behind its last row, and every following export with that cursor
        // carries the next, older slice — the "total" shrinking to what is
        // left each time — until a slice arrives uncapped, which ends the
        // walk.
        MvcResult first = mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(header().string("X-Logos-Export-Total", "8"))
           .andExpect(header().string("X-Logos-Export-Count", "2"))
           .andExpect(jsonPath("$.traces[0].request_id").value("req-trunc-040"))
           .andExpect(jsonPath("$.traces[1].request_id").value("req-trunc-041"))
           .andReturn();
        String next = first.getResponse().getHeader("X-Logos-Export-Next-Cursor");
        assertNotNull(next);
        // The envelope and the header name the same continuation, so a file
        // opened later says how to reach the rows it does not hold.
        assertEquals(next, JsonPath.parse(first.getResponse().getContentAsString()).read("$.next_cursor"));

        // Slice two. Its two rows sit at the same minute from two different
        // seed scripts, so their order is a coin flip — the set is not. And
        // its newest row is the consented one, so the slice carries content
        // and the file has no note to make.
        MvcResult second = mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content(cursorBody(next)))
           .andExpect(status().isOk())
           .andExpect(header().string("X-Logos-Export-Total", "6"))
           .andExpect(header().string("X-Logos-Export-Truncated", "true"))
           .andExpect(header().string("X-Logos-Export-Count", "2"))
           .andExpect(header().exists("X-Logos-Export-Next-Cursor"))
           .andExpect(jsonPath("$.total_in_window").value(6))
           .andExpect(jsonPath("$.next_cursor").isNotEmpty())
           .andExpect(jsonPath("$.note").doesNotExist())
           .andReturn();
        List<String> secondIds = JsonPath.parse(second.getResponse().getContentAsString())
            .read("$.traces[*].request_id");
        Collections.sort(secondIds);
        assertEquals(List.of("req-ddd-444", "req-trunc-042"), secondIds);

        // Slices three and four: past the tied pair the order is settled
        // again, and the last slice fits the cap, so the walk ends with no
        // continuation left to hand back.
        String nextTwo = second.getResponse().getHeader("X-Logos-Export-Next-Cursor");
        MvcResult third = mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content(cursorBody(nextTwo)))
           .andExpect(status().isOk())
           .andExpect(header().string("X-Logos-Export-Total", "4"))
           .andExpect(header().string("X-Logos-Export-Truncated", "true"))
           .andExpect(jsonPath("$.traces[0].request_id").value("req-trunc-043"))
           .andExpect(jsonPath("$.traces[1].request_id").value("req-trunc-044"))
           .andReturn();
        String nextThree = third.getResponse().getHeader("X-Logos-Export-Next-Cursor");
        mvc.perform(post("/logosdb/teams/2001/activity/export")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content(cursorBody(nextThree)))
           .andExpect(status().isOk())
           .andExpect(header().string("X-Logos-Export-Total", "2"))
           .andExpect(header().string("X-Logos-Export-Truncated", "false"))
           .andExpect(header().string("X-Logos-Export-Count", "2"))
           .andExpect(header().doesNotExist("X-Logos-Export-Next-Cursor"))
           .andExpect(jsonPath("$.truncated").value(false))
           .andExpect(jsonPath("$.total_in_window").value(2))
           .andExpect(jsonPath("$.next_cursor").doesNotExist())
           .andExpect(jsonPath("$.traces[0].request_id").value("req-ccc-333"))
           .andExpect(jsonPath("$.traces[1].request_id").value("req-aaa-111"));
    }

    /** The cursor token the server sent, back in the body's two fields. */
    private static String cursorBody(String token) {
        int sep = token.lastIndexOf('/');
        return "{\"cursor_ts\": \"" + token.substring(0, sep) + "\", \"cursor_id\": "
            + token.substring(sep + 1) + "}";
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
