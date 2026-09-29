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

/**
 * The sampling behind the most asked questions.
 *
 * The section ranks the newest consented rows of the window, not the whole
 * window: parsing the stored JSONB of every FULL row of a busy ninety days is
 * the computation that keeps the tab from loading. This class shrinks the
 * sample to two rows and seeds three, so the test pins down which rows the
 * sample keeps — the newest, not the loudest or the oldest.
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
    "logos.team-activity.most-asked-scan-limit=2"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-operations.sql",
     "/sql/seed-operations-most-asked-scan-limit.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-operations.sql", "/sql/cleanup-configuration.sql",
     "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class TeamActivityMostAskedScanLimitTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void theSampleKeepsTheNewestConsentedRowsOnly() throws Exception {
        // Three FULL rows, three different questions, a sample of two: the
        // digest holds the two newest, and the oldest question falls out
        // rather than stretching the query over the whole window.
        mvc.perform(post("/logosdb/teams/2001/activity")
                .with(TestJwt.adminUser())
                .contentType("application/json")
                .content("{}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.most_asked_questions.length()").value(2))
           .andExpect(jsonPath("$.most_asked_questions[0].question")
               .value("Which one is the middle question?"))
           .andExpect(jsonPath("$.most_asked_questions[0].count").value(1))
           .andExpect(jsonPath("$.most_asked_questions[1].question")
               .value("Which one is the newest question?"))
           .andExpect(jsonPath("$.most_asked_questions[1].count").value(1))
           // The view labels the ranking with the limit that cut it — and
           // that limit is the shrunk one, not the default.
           .andExpect(jsonPath("$.most_asked_sample_limit").value(2));
    }
}
