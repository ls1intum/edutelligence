package de.tum.cit.aet.logos.logoswebservice.notifications.controller;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

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

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.TestJwt;

/**
 * The user's inbox over HTTP: role/team/user targeting on the list, the
 * computed unread count, and the read markers. Requests are authenticated as
 * the seeded users (testuser=1001 developer, adminuser=1002 app admin,
 * logosadmin=1003 logos admin, all in team 2001).
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
    "logos.orchestrator.url=",
    "logos.orchestrator.internal-secret=test-internal-secret"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-notifications.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-notifications.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class NotificationControllerTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void developerSeesOnlyTheTeamTargetedItem() throws Exception {
        mvc.perform(get("/me/notifications").with(TestJwt.testUser()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.total_elements").value(1))
           .andExpect(jsonPath("$.content[0].id").value(9002))
           .andExpect(jsonPath("$.content[0].type").value("new_models_available"));
    }

    @Test
    void logosAdminSeesRoleTeamAndUserItems() throws Exception {
        mvc.perform(get("/me/notifications").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.total_elements").value(3));
    }

    @Test
    void unreadCountReflectsReadState() throws Exception {
        // 1002: 9001 read, 9002 unread -> 1.
        mvc.perform(get("/me/notifications/unread-count").with(TestJwt.adminUser()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").value(1));
    }

    @Test
    void markReadThenUnreadCountDrops() throws Exception {
        mvc.perform(post("/me/notifications/9002/read").with(TestJwt.adminUser()))
           .andExpect(status().isOk());
        mvc.perform(get("/me/notifications/unread-count").with(TestJwt.adminUser()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").value(0));
    }

    @Test
    void markReadMissingNotificationIs404() throws Exception {
        mvc.perform(post("/me/notifications/99999/read").with(TestJwt.adminUser()))
           .andExpect(status().isNotFound());
    }

    @Test
    void markReadUnaddressedNotificationIs404() throws Exception {
        // 9001 targets the app_admin role; testuser is an app_developer.
        mvc.perform(post("/me/notifications/9001/read").with(TestJwt.testUser()))
           .andExpect(status().isNotFound());
    }

    @Test
    void oversizedPageIsBadRequest() throws Exception {
        mvc.perform(get("/me/notifications").param("size", "101").with(TestJwt.testUser()))
           .andExpect(status().isBadRequest());
    }

    @Test
    void markAllReadClearsTheUsersInbox() throws Exception {
        mvc.perform(post("/me/notifications/read-all").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk());
        mvc.perform(get("/me/notifications/unread-count").with(TestJwt.logosAdmin()))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$").value(0));
    }
}
