package de.tum.cit.aet.logos.logoswebservice.identity.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Map;
import java.util.Optional;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

import de.tum.cit.aet.logos.logoswebservice.audit.AuditLogService;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateApiKeyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.LogLevel;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

/** Both log-level setters and the key update leave a record, and only for a real change. */
class ApiKeyAdminServiceAuditTest {

    private NamedParameterJdbcTemplate jdbc;
    private ApiKeyRepository keys;
    private ApiKeyAdminService service;
    private ApiKey key;

    @BeforeEach
    void setUp() {
        jdbc = mock(NamedParameterJdbcTemplate.class);
        keys = mock(ApiKeyRepository.class);
        AuditLogService audit = new AuditLogService(jdbc, mock(UserRepository.class));
        service = new ApiKeyAdminService(keys, mock(TeamRepository.class), mock(TeamMemberRepository.class), audit);
        key = new ApiKey();
        key.setTeamId(3);
        key.setLog(LogLevel.BILLING);
        key.setSettings("{\"cloud_rpm_limit\":10}");
        when(keys.findById(5)).thenReturn(Optional.of(key));
    }

    @Test
    void legacySetLogRecordsTheChange() {
        service.setLog(5, "FULL");

        ArgumentCaptor<MapSqlParameterSource> params = ArgumentCaptor.forClass(MapSqlParameterSource.class);
        verify(jdbc).update(anyString(), params.capture());
        assertThat(params.getValue().getValue("action")).isEqualTo("api_key.log_level_changed");
        assertThat(params.getValue().getValue("teamId")).isEqualTo(3);
        assertThat((String) params.getValue().getValue("before")).contains("BILLING");
        assertThat((String) params.getValue().getValue("after")).contains("FULL");
    }

    @Test
    void legacySetLogToTheSameLevelRecordsNothing() {
        service.setLog(5, "BILLING");

        verify(jdbc, never()).update(anyString(), any(MapSqlParameterSource.class));
    }

    @Test
    void resavingUnchangedLimitsRecordsNothing() {
        service.updateKey(5, new UpdateApiKeyRequestDTO(null, null, null, null, 10, null, null, null, null));

        verify(jdbc, never()).update(anyString(), any(MapSqlParameterSource.class));
        verify(keys).save(eq(key));
    }
}
