package de.tum.cit.aet.logos.logoswebservice.notifications.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.after;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.notifications.dto.NotificationResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.notifications.dto.NotificationTargetDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.notifications.dto.PublishNotificationRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationType;
import de.tum.cit.aet.logos.logoswebservice.notifications.realtime.NotificationSocketHandler;

/**
 * The publish and read halves against a real (Testcontainers) database:
 * fan-out visibility by user/team/role, the computed unread state, and the
 * publish validation. Starting state comes from seed-notifications.sql.
 */
@SpringBootTest
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
class NotificationServiceTest {

    @Autowired NotificationService service;
    @Autowired JdbcTemplate jdbc;
    @Autowired NotificationSocketHandler sockets;
    @MockitoBean JwtDecoder jwtDecoder;

    private static final List<Integer> TEAM = List.of(2001);

    @Test
    void listMine_appliesRoleTeamAndUserTargeting() {
        // 1001 (app_developer, team 2001) sees only 9002 (team target).
        Page<NotificationResponseDTO> dev = service.listMine(1001, "app_developer", TEAM, false, PageRequest.of(0, 50));
        assertThat(dev.getTotalElements()).isEqualTo(1);
        assertThat(dev.getContent().get(0).id()).isEqualTo(9002L);

        // 1002 (app_admin, team 2001) sees 9001 (role) and 9002 (team).
        Page<NotificationResponseDTO> admin = service.listMine(1002, "app_admin", TEAM, false, PageRequest.of(0, 50));
        assertThat(admin.getTotalElements()).isEqualTo(2);
        assertThat(admin.getContent()).extracting(NotificationResponseDTO::id)
            .containsExactlyInAnyOrder(9001L, 9002L);

        // 1003 (logos_admin, team 2001) sees 9002 (team), 9003 (user), 9004 (role).
        Page<NotificationResponseDTO> logos = service.listMine(1003, "logos_admin", TEAM, false, PageRequest.of(0, 50));
        assertThat(logos.getTotalElements()).isEqualTo(3);
        assertThat(logos.getContent()).extracting(NotificationResponseDTO::id)
            .containsExactlyInAnyOrder(9002L, 9003L, 9004L);
    }

    @Test
    void userWithoutTeamsSeesOnlyDirectAndRoleItems() {
        // 1005 (app_developer) has no team memberships: the team match runs
        // against an empty id list and must simply match nothing.
        Page<NotificationResponseDTO> none = service.listMine(1005, "app_developer", List.of(), false, PageRequest.of(0, 50));
        assertThat(none.getTotalElements()).isZero();
        assertThat(service.unreadCount(1005, "app_developer", List.of())).isZero();
        assertThat(service.markRead(1005, "app_developer", List.of(), 9002L)).isFalse();
        service.markAllRead(1005, "app_developer");
    }

    @Test
    void unreadCount_countsOnlyUnreadForTheUser() {
        // 1002 sees 9001 (read) and 9002 (unread) -> 1.
        assertThat(service.unreadCount(1002, "app_admin", TEAM)).isEqualTo(1);
        // 1001 sees only 9002 (unread) -> 1.
        assertThat(service.unreadCount(1001, "app_developer", TEAM)).isEqualTo(1);
        // 1003 sees 9002, 9003, 9004, all unread -> 3.
        assertThat(service.unreadCount(1003, "logos_admin", TEAM)).isEqualTo(3);
    }

    @Test
    void listMine_unreadOnlyFiltersOutReadItems() {
        // 1002: 9001 read, 9002 unread -> unreadOnly returns just 9002.
        Page<NotificationResponseDTO> unread = service.listMine(1002, "app_admin", TEAM, true, PageRequest.of(0, 50));
        assertThat(unread.getTotalElements()).isEqualTo(1);
        assertThat(unread.getContent().get(0).id()).isEqualTo(9002L);
        assertThat(unread.getContent().get(0).read()).isFalse();
    }

    @Test
    void markRead_marksItemReadAndIsIdempotent() {
        assertThat(service.markRead(1002, "app_admin", TEAM, 9002L)).isTrue();
        assertThat(service.unreadCount(1002, "app_admin", TEAM)).isEqualTo(0);
        // Already read: still a success, count stays 0.
        assertThat(service.markRead(1002, "app_admin", TEAM, 9002L)).isTrue();
        assertThat(service.unreadCount(1002, "app_admin", TEAM)).isEqualTo(0);
    }

    @Test
    void markRead_missingNotificationReportsFalse() {
        assertThat(service.markRead(1002, "app_admin", TEAM, 99999L)).isFalse();
    }

    @Test
    void markRead_unaddressedNotificationReportsFalseAndStoresNothing() {
        // 9001 targets the app_admin role; 1001 is an app_developer.
        assertThat(service.markRead(1001, "app_developer", TEAM, 9001L)).isFalse();
        Integer markers = jdbc.queryForObject(
            "SELECT COUNT(*) FROM notification_reads WHERE user_id = 1001", Integer.class);
        assertThat(markers).isZero();
    }

    @Test
    void overlappingReadRequestsNeverFail() throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(4);
        try {
            for (int round = 0; round < 10; round++) {
                jdbc.update("DELETE FROM notification_reads WHERE user_id = 1003");
                CountDownLatch start = new CountDownLatch(1);
                List<Future<?>> runs = new ArrayList<>();
                for (int i = 0; i < 2; i++) {
                    runs.add(pool.submit(() -> {
                        start.await();
                        service.markAllRead(1003, "logos_admin");
                        return null;
                    }));
                    runs.add(pool.submit(() -> {
                        start.await();
                        return service.markRead(1003, "logos_admin", TEAM, 9002L);
                    }));
                }
                start.countDown();
                for (Future<?> run : runs) {
                    run.get(); // rethrows a failed request
                }
                assertThat(service.unreadCount(1003, "logos_admin", TEAM)).isZero();
            }
        } finally {
            pool.shutdownNow();
        }
    }

    @Test
    void markAllRead_marksEveryAddressedItemForThatUserOnly() {
        service.markAllRead(1003, "logos_admin");
        assertThat(service.unreadCount(1003, "logos_admin", TEAM)).isEqualTo(0);
        // 1002 is untouched by 1003's mark-all-read.
        assertThat(service.unreadCount(1002, "app_admin", TEAM)).isEqualTo(1);
    }

    @Test
    void publish_persistsAndFansOutByRole() {
        PublishNotificationRequestDTO req = new PublishNotificationRequestDTO(
            "budget_hit", "Budget hit", "over", Map.of("team_id", 2001),
            "orchestrator", 1001,
            List.of(new NotificationTargetDTO("role", null, "app_admin")));
        long id = service.publish(req);
        assertThat(id).isPositive();

        // The new role-targeted item is unread for 1002 (app_admin): was 1, now 2.
        assertThat(service.unreadCount(1002, "app_admin", TEAM)).isEqualTo(2);
        // 1001 (app_developer) is not addressed by the role target: still 1.
        assertThat(service.unreadCount(1001, "app_developer", TEAM)).isEqualTo(1);
    }

    private WebSocketSession openSocket(String id, int userId) {
        WebSocketSession session = mock(WebSocketSession.class);
        Map<String, Object> attributes = new HashMap<>();
        attributes.put("notificationUserId", userId);
        when(session.getId()).thenReturn(id);
        when(session.getAttributes()).thenReturn(attributes);
        when(session.isOpen()).thenReturn(true);
        sockets.afterConnectionEstablished(session);
        return session;
    }

    private void publishToTeam2001() {
        service.publish(new PublishNotificationRequestDTO(
            "new_models_available", "New models", null, null, "webservice", null,
            List.of(new NotificationTargetDTO("team", 2001, null))));
    }

    @Test
    void publish_pushesToTheOpenSocketsOfItsRecipients() throws Exception {
        WebSocketSession appAdmin = openSocket("push-role", 1002);
        WebSocketSession outsider = openSocket("push-outsider", 1006);
        try {
            service.publish(new PublishNotificationRequestDTO(
                "budget_hit", "Budget hit", null, null, "webservice", null,
                List.of(new NotificationTargetDTO("role", null, "app_admin"))));
            // Delivered after the publishing transaction commits.
            verify(appAdmin, timeout(2_000)).sendMessage(any(TextMessage.class));
            verify(outsider, after(300).never()).sendMessage(any(TextMessage.class));
        } finally {
            sockets.afterConnectionClosed(appAdmin, CloseStatus.NORMAL);
            sockets.afterConnectionClosed(outsider, CloseStatus.NORMAL);
        }
    }

    @Test
    void openSocketStopsReceivingTeamItemsAfterLeavingTheTeam() throws Exception {
        WebSocketSession developer = openSocket("revoke-team", 1001);
        try {
            publishToTeam2001();
            verify(developer, timeout(2_000).times(1)).sendMessage(any(TextMessage.class));

            jdbc.update("DELETE FROM team_members WHERE user_id = 1001 AND team_id = 2001");
            publishToTeam2001();
            verify(developer, after(500).times(1)).sendMessage(any(TextMessage.class));
        } finally {
            sockets.afterConnectionClosed(developer, CloseStatus.NORMAL);
        }
    }

    @Test
    void openSocketStopsReceivingAfterTheUserIsDeactivated() throws Exception {
        WebSocketSession developer = openSocket("revoke-active", 1001);
        try {
            jdbc.update("UPDATE users SET is_active = false WHERE id = 1001");
            publishToTeam2001();
            verify(developer, after(500).never()).sendMessage(any(TextMessage.class));
        } finally {
            jdbc.update("UPDATE users SET is_active = true WHERE id = 1001");
            sockets.afterConnectionClosed(developer, CloseStatus.NORMAL);
        }
    }

    @Test
    void markAllRead_skipsHistoryAlreadyRead() {
        // 1002 already read 9001; only 9002 is added.
        service.markAllRead(1002, "app_admin");
        assertThat(jdbc.queryForObject(
            "SELECT COUNT(*) FROM notification_reads WHERE user_id = 1002", Integer.class)).isEqualTo(2);
        assertThat(service.unreadCount(1002, "app_admin", TEAM)).isZero();
    }

    @Test
    void publish_storesPayloadAsJsonObject() {
        long id = service.publish(new PublishNotificationRequestDTO(
            "budget_hit", "Budget hit", null, Map.of("team_id", 2001), "webservice", null,
            List.of(new NotificationTargetDTO("role", null, "app_admin"))));
        String shape = jdbc.queryForObject(
            "SELECT jsonb_typeof(payload) FROM notifications WHERE id = ?", String.class, id);
        assertThat(shape).isEqualTo("object");
    }

    @Test
    void publish_collapsesRepeatedTargets() {
        long id = service.publish(new PublishNotificationRequestDTO(
            "budget_hit", "Budget hit", null, null, "webservice", null,
            List.of(new NotificationTargetDTO("team", 2001, null),
                    new NotificationTargetDTO("team", 2001, null))));
        Integer rows = jdbc.queryForObject(
            "SELECT COUNT(*) FROM notification_recipients WHERE notification_id = ?", Integer.class, id);
        assertThat(rows).isEqualTo(1);
    }

    @Test
    void publish_rejectsIncompleteTargetsWithoutPersisting() {
        long before = jdbc.queryForObject("SELECT COUNT(*) FROM notifications", Long.class);
        List<NotificationTargetDTO> invalid = new ArrayList<>(List.of(
            new NotificationTargetDTO("user", null, null),
            new NotificationTargetDTO("team", null, null),
            new NotificationTargetDTO("role", null, null),
            new NotificationTargetDTO("role", null, "not_a_role"),
            new NotificationTargetDTO(null, 1001, null)));
        invalid.add(null);
        for (NotificationTargetDTO target : invalid) {
            List<NotificationTargetDTO> targets = new ArrayList<>();
            targets.add(target);
            assertThatThrownBy(() -> service.publish(new PublishNotificationRequestDTO(
                "budget_hit", "Title", null, null, "webservice", null, targets)))
                .isInstanceOf(IllegalArgumentException.class);
        }
        assertThatThrownBy(() -> service.publish(new PublishNotificationRequestDTO(
            null, "Title", null, null, "webservice", null,
            List.of(new NotificationTargetDTO("role", null, "app_admin")))))
            .isInstanceOf(IllegalArgumentException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM notifications", Long.class)).isEqualTo(before);
    }

    @Test
    void publish_rejectsUnknownType() {
        PublishNotificationRequestDTO req = new PublishNotificationRequestDTO(
            "nope", "Title", null, null, "webservice", null,
            List.of(new NotificationTargetDTO("role", null, "app_admin")));
        assertThatThrownBy(() -> service.publish(req))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessageContaining("Unknown notification type");
    }

    @Test
    void publish_rejectsMissingTitle() {
        PublishNotificationRequestDTO req = new PublishNotificationRequestDTO(
            "budget_hit", "  ", null, null, "webservice", null,
            List.of(new NotificationTargetDTO("role", null, "app_admin")));
        assertThatThrownBy(() -> service.publish(req))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessageContaining("title");
    }

    @Test
    void publish_rejectsNoTargets() {
        PublishNotificationRequestDTO req = new PublishNotificationRequestDTO(
            "budget_hit", "Title", null, null, "webservice", null, List.of());
        assertThatThrownBy(() -> service.publish(req))
            .isInstanceOf(IllegalArgumentException.class)
            .hasMessageContaining("target");
    }
}
