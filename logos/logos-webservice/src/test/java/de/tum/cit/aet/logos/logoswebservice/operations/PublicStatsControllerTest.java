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
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;

/**
 * /public/stats is the aggregate picture of the platform for people who
 * have not signed in. The fixtures mix successes with an error and a
 * timeout that share the key, team and provider of successful rows — the
 * asserted totals are what you get when only the successes count.
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
    void unauthenticatedClientGetsSuccessOnlyAggregates() throws Exception {
        // 1004 is the seeded inactive user: five registered students, two teams.
        // Successes: 9101/9102/9107 (team 2001, developer key) and
        // 9105/9106 (team 2002, application key). 9103 (error) and 9104
        // (timeout) would move every total below if counted.
        mvc.perform(get("/public/stats"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.students").value(5))
           .andExpect(jsonPath("$.teams").value(2))
           .andExpect(jsonPath("$.successful_requests").value(5))
           .andExpect(jsonPath("$.average_requests_per_user").value(1.0))
           .andExpect(jsonPath("$.requests_per_team.length()").value(2))
           .andExpect(jsonPath("$.requests_per_team[0].team_id").value(2001))
           .andExpect(jsonPath("$.requests_per_team[0].team_name").value("test-team"))
           .andExpect(jsonPath("$.requests_per_team[0].requests").value(3))
           .andExpect(jsonPath("$.requests_per_team[1].team_id").value(2002))
           .andExpect(jsonPath("$.requests_per_team[1].team_name").value("kc-team"))
           .andExpect(jsonPath("$.requests_per_team[1].requests").value(2))
           .andExpect(jsonPath("$.requests_by_key_type.developer").value(3))
           .andExpect(jsonPath("$.requests_by_key_type.application").value(2))
           .andExpect(jsonPath("$.requests_by_key_type.service").value(0))
           .andExpect(jsonPath("$.local_cloud_requests.local").value(1))
           .andExpect(jsonPath("$.local_cloud_requests.cloud").value(4));
    }

    @Test
    void aValidJwtGetsTheSameView() throws Exception {
        mvc.perform(get("/public/stats").with(TestJwt.testUser()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.students").value(5))
           .andExpect(jsonPath("$.teams").value(2));
    }

    @Test
    void aPlatformWithoutTrafficReportsZeroes() throws Exception {
        mvc.perform(get("/public/stats"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.students").value(5))
           .andExpect(jsonPath("$.teams").value(2))
           .andExpect(jsonPath("$.successful_requests").value(0))
           .andExpect(jsonPath("$.average_requests_per_user").value(0.0))
           .andExpect(jsonPath("$.requests_per_team").isEmpty())
           .andExpect(jsonPath("$.requests_by_key_type.developer").value(0))
           .andExpect(jsonPath("$.requests_by_key_type.application").value(0))
           .andExpect(jsonPath("$.requests_by_key_type.service").value(0))
           .andExpect(jsonPath("$.local_cloud_requests.local").value(0))
           .andExpect(jsonPath("$.local_cloud_requests.cloud").value(0));
    }
}
