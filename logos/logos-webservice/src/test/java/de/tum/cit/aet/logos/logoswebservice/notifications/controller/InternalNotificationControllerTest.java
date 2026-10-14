package de.tum.cit.aet.logos.logoswebservice.notifications.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.web.servlet.MockMvc;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationType;
import de.tum.cit.aet.logos.logoswebservice.notifications.repository.NotificationRecipientRepository;
import de.tum.cit.aet.logos.logoswebservice.notifications.repository.NotificationRepository;

/**
 * The orchestrator's emission door: it authenticates with the internal secret
 * as a Bearer token (not a JWT), forces the source to {@code orchestrator},
 * and validates the payload. Exercises the whole filter chain, like
 * InternalModelControllerTest does for models_discovered.
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
class InternalNotificationControllerTest {

    @Autowired MockMvc mvc;
    @Autowired NotificationRepository notifications;
    @Autowired NotificationRecipientRepository recipients;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void internalSecretPublishesWithForcedOrchestratorSource() throws Exception {
        mvc.perform(post("/internal/notifications")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"type\":\"batch_job_finished\",\"title\":\"Batch done\","
                    + "\"payload\":{\"job_id\":7},"
                    + "\"targets\":[{\"kind\":\"team\",\"id\":2001}]}"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.status").value("accepted"));

        var batch = notifications.findAll().stream()
            .filter(n -> n.getType() == NotificationType.batch_job_finished)
            .toList();
        assertThat(batch).hasSize(1);
        assertThat(batch.get(0).getSource()).isEqualTo("orchestrator");
        // It is addressed to team 2001.
        var target = recipients.findAll().stream()
            .filter(r -> r.getNotificationId().equals(batch.get(0).getId()))
            .toList();
        assertThat(target).hasSize(1);
        assertThat(target.get(0).getRecipientId()).isEqualTo(2001);
    }

    @Test
    void wrongSecretIsRejected() throws Exception {
        mvc.perform(post("/internal/notifications")
                .header("Authorization", "Bearer wrong-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"type\":\"budget_hit\",\"title\":\"x\","
                    + "\"targets\":[{\"kind\":\"role\",\"role\":\"app_admin\"}]}"))
           .andExpect(status().isUnauthorized());
        // The seed created exactly four; the rejected request added none.
        assertThat(notifications.count()).isEqualTo(4L);
    }

    @Test
    void missingAuthorizationIsRejected() throws Exception {
        mvc.perform(post("/internal/notifications")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"type\":\"budget_hit\",\"title\":\"x\","
                    + "\"targets\":[{\"kind\":\"role\",\"role\":\"app_admin\"}]}"))
           .andExpect(status().isUnauthorized());
    }

    @Test
    void unknownTypeIsBadRequest() throws Exception {
        mvc.perform(post("/internal/notifications")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"type\":\"nope\",\"title\":\"x\","
                    + "\"targets\":[{\"kind\":\"role\",\"role\":\"app_admin\"}]}"))
           .andExpect(status().isBadRequest());
    }

    @Test
    void incompleteTargetIsBadRequestAndStoresNothing() throws Exception {
        mvc.perform(post("/internal/notifications")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"type\":\"budget_hit\",\"title\":\"x\","
                    + "\"targets\":[{\"kind\":\"user\"}]}"))
           .andExpect(status().isBadRequest());
        assertThat(notifications.count()).isEqualTo(4L);
    }

    @Test
    void noTargetsIsBadRequest() throws Exception {
        mvc.perform(post("/internal/notifications")
                .header("Authorization", "Bearer test-internal-secret")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"type\":\"budget_hit\",\"title\":\"x\",\"targets\":[]}"))
           .andExpect(status().isBadRequest());
    }
}
