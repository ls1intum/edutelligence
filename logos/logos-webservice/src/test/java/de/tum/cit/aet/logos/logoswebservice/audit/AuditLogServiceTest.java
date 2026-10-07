package de.tum.cit.aet.logos.logoswebservice.audit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

class AuditLogServiceTest {

    private NamedParameterJdbcTemplate jdbc;
    private UserRepository users;
    private AuditLogService service;

    @BeforeEach
    void setUp() {
        jdbc = mock(NamedParameterJdbcTemplate.class);
        users = mock(UserRepository.class);
        service = new AuditLogService(jdbc, users);
    }

    @AfterEach
    void clearRequest() {
        RequestContextHolder.resetRequestAttributes();
    }

    private void asRequestBy(int userId, String role, String username) {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setAttribute("authContext", new AuthContext(userId, role));
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        User user = mock(User.class);
        when(user.getUsername()).thenReturn(username);
        when(users.findById(userId)).thenReturn(Optional.of(user));
    }

    private static Map<String, Object> map(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i < kv.length; i += 2) {
            m.put((String) kv[i], kv[i + 1]);
        }
        return m;
    }

    @Test
    void unchangedSettingsLeaveNoTrace() {
        service.record("team.limits_updated", "team", 1, 1, map("a", 5L), map("a", 5L));

        verify(jdbc, never()).update(anyString(), any(MapSqlParameterSource.class));
    }

    @Test
    void recordsActorAndOnlyTheChangedFields() {
        asRequestBy(7, "app_admin", "owner@tum.de");

        service.record("team.limits_updated", "team", 3, 3,
            map("team_monthly_budget_micro_cents", 100L, "default_cloud_rpm_limit", 10),
            map("team_monthly_budget_micro_cents", 900L, "default_cloud_rpm_limit", 10));

        ArgumentCaptor<MapSqlParameterSource> params = ArgumentCaptor.forClass(MapSqlParameterSource.class);
        verify(jdbc).update(anyString(), params.capture());
        MapSqlParameterSource p = params.getValue();
        assertThat(p.getValue("actorId")).isEqualTo(7);
        assertThat(p.getValue("actorName")).isEqualTo("owner@tum.de");
        assertThat(p.getValue("actorRole")).isEqualTo("app_admin");
        assertThat(p.getValue("action")).isEqualTo("team.limits_updated");
        assertThat(p.getValue("teamId")).isEqualTo(3);
        assertThat((String) p.getValue("before")).contains("\"team_monthly_budget_micro_cents\":100")
            .doesNotContain("default_cloud_rpm_limit");
        assertThat((String) p.getValue("after")).contains("\"team_monthly_budget_micro_cents\":900")
            .doesNotContain("default_cloud_rpm_limit");
    }

    @Test
    void outsideARequestTheActorIsEmptyButTheChangeIsStillRecorded() {
        service.record("api_key.log_level_changed", "api_key", 4, null,
            map("log", "BILLING"), map("log", "FULL"));

        ArgumentCaptor<MapSqlParameterSource> params = ArgumentCaptor.forClass(MapSqlParameterSource.class);
        verify(jdbc).update(anyString(), params.capture());
        assertThat(params.getValue().getValue("actorId")).isNull();
        assertThat(params.getValue().getValue("targetId")).isEqualTo("4");
    }

    @Test
    void listCapsThePageSize() {
        service.list(5, null, 10_000);

        ArgumentCaptor<MapSqlParameterSource> params = ArgumentCaptor.forClass(MapSqlParameterSource.class);
        verify(jdbc).queryForList(anyString(), params.capture());
        assertThat(params.getValue().getValue("size")).isEqualTo(AuditLogService.MAX_PAGE);
        assertThat(params.getValue().getValue("teamId")).isEqualTo(5);
    }
}
