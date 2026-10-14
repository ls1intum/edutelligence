package de.tum.cit.aet.logos.logoswebservice.notifications.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.notifications.dto.NotificationResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.notifications.dto.NotificationTargetDTO;
import de.tum.cit.aet.logos.logoswebservice.notifications.dto.PublishNotificationRequestDTO;

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
        assertThat(service.markRead(1002, 9002L)).isTrue();
        assertThat(service.unreadCount(1002, "app_admin", TEAM)).isEqualTo(0);
        // Already read: still a success, count stays 0.
        assertThat(service.markRead(1002, 9002L)).isTrue();
        assertThat(service.unreadCount(1002, "app_admin", TEAM)).isEqualTo(0);
    }

    @Test
    void markRead_missingNotificationReportsFalse() {
        assertThat(service.markRead(1002, 99999L)).isFalse();
    }

    @Test
    void markAllRead_marksEveryAddressedItemForThatUserOnly() {
        service.markAllRead(1003, "logos_admin", TEAM);
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
