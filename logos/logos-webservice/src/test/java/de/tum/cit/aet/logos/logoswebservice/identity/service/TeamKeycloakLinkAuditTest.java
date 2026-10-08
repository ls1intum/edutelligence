package de.tum.cit.aet.logos.logoswebservice.identity.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import de.tum.cit.aet.logos.logoswebservice.audit.AuditLogService;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TeamModelPermissionRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberSource;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.TeamBudgetRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

/**
 * The Keycloak link decides who joins a team and who holds its developer keys,
 * so a change to it belongs in the same trail as the budgets it governs.
 */
class TeamKeycloakLinkAuditTest {

    private TeamRepository teams;
    private TeamMemberRepository members;
    private KeycloakGroupLinkNormalizer normalizer;
    private AuditLogService audit;
    private TeamService service;

    @BeforeEach
    void setUp() {
        teams = mock(TeamRepository.class);
        members = mock(TeamMemberRepository.class);
        normalizer = mock(KeycloakGroupLinkNormalizer.class);
        audit = mock(AuditLogService.class);
        when(teams.saveAndFlush(any(Team.class))).thenAnswer(i -> i.getArgument(0));
        when(members.findById_TeamIdAndSource(any(), eq(TeamMemberSource.KEYCLOAK)))
            .thenReturn(List.of());
        service = new TeamService(teams, members, mock(UserRepository.class),
            mock(TeamBudgetRepository.class), mock(TeamModelPermissionRepository.class),
            mock(ApiKeyRepository.class), mock(TeamMembershipService.class), normalizer, audit);
    }

    private void linkedTo(String group) {
        Team team = mock(Team.class);
        when(team.getId()).thenReturn(3);
        when(team.getName()).thenReturn("T");
        when(team.getKeycloakGroup()).thenReturn(group);
        when(teams.findByIdForUpdate(3)).thenReturn(Optional.of(team));
    }

    @Test
    @SuppressWarnings("unchecked")
    void linkingATeamIsAudited() {
        linkedTo(null);
        when(normalizer.normalize("ios-26ws")).thenReturn("ios-26ws");
        when(teams.findByKeycloakGroup("ios-26ws")).thenReturn(Optional.empty());

        service.updateTeamKeycloakGroup(3, "ios-26ws");

        ArgumentCaptor<Map<String, Object>> before = ArgumentCaptor.forClass(Map.class);
        ArgumentCaptor<Map<String, Object>> after = ArgumentCaptor.forClass(Map.class);
        verify(audit).record(eq("team.keycloak_group_changed"), eq("team"), eq(3), eq(3),
            before.capture(), after.capture());
        assertThat(before.getValue()).containsEntry("keycloak_group", "");
        assertThat(after.getValue()).containsEntry("keycloak_group", "ios-26ws");
    }

    @Test
    @SuppressWarnings("unchecked")
    void unlinkingATeamIsAudited() {
        linkedTo("ios-26ws");
        when(normalizer.normalize(null)).thenReturn(null);

        service.updateTeamKeycloakGroup(3, null);

        ArgumentCaptor<Map<String, Object>> before = ArgumentCaptor.forClass(Map.class);
        ArgumentCaptor<Map<String, Object>> after = ArgumentCaptor.forClass(Map.class);
        verify(audit).record(eq("team.keycloak_group_changed"), eq("team"), eq(3), eq(3),
            before.capture(), after.capture());
        assertThat(before.getValue()).containsEntry("keycloak_group", "ios-26ws");
        assertThat(after.getValue()).containsEntry("keycloak_group", "");
    }

    /** Saving the settings form without touching the field must leave no trace. */
    @Test
    void resavingTheSameLinkIsNotAudited() {
        linkedTo("ios-26ws");
        when(normalizer.normalize("ios-26ws")).thenReturn("ios-26ws");

        service.updateTeamKeycloakGroup(3, "ios-26ws");

        verify(audit, never()).record(any(), any(), any(), any(), any(), any());
    }
}
