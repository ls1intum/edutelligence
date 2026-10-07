package de.tum.cit.aet.logos.logoswebservice.identity.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import de.tum.cit.aet.logos.logoswebservice.audit.AuditLogService;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMember;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberId;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberSource;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;

/** Who is in a team, and who owns it, decides who can change its budget, so it is audited. */
class TeamMembershipServiceAuditTest {

    private TeamMemberRepository members;
    private UserRepository users;
    private TeamRepository teams;
    private ApiKeyFactory keyFactory;
    private AuditLogService audit;
    private TeamMembershipService service;

    @BeforeEach
    void setUp() {
        members = mock(TeamMemberRepository.class);
        users = mock(UserRepository.class);
        teams = mock(TeamRepository.class);
        keyFactory = mock(ApiKeyFactory.class);
        audit = mock(AuditLogService.class);
        ApiKeyRepository keys = mock(ApiKeyRepository.class);
        when(keys.findByUserIdAndTeamIdAndKeyType(any(), any(), any())).thenReturn(List.of());
        service = new TeamMembershipService(members, keys, users, teams, keyFactory, audit);
    }

    private static TeamMember member(int userId, int teamId, boolean owner, TeamMemberSource source) {
        TeamMember m = new TeamMember();
        m.setId(new TeamMemberId(userId, teamId));
        m.setIsOwner(owner);
        m.setSource(source);
        return m;
    }

    @Test
    @SuppressWarnings("unchecked")
    void joiningATeamAsOwnerIsAudited() {
        User user = mock(User.class);
        when(user.getUsername()).thenReturn("alice");
        Team team = mock(Team.class);
        when(team.getName()).thenReturn("T");
        when(users.findById(7)).thenReturn(Optional.of(user));
        when(teams.findById(3)).thenReturn(Optional.of(team));
        when(members.findById(new TeamMemberId(7, 3))).thenReturn(Optional.empty());
        ApiKey newKey = new ApiKey();
        newKey.setKeyValue("lg-test");
        when(keyFactory.createDeveloperKey(user, team)).thenReturn(newKey);

        service.join(7, 3, true, TeamMemberSource.MANUAL);

        ArgumentCaptor<Map<String, Object>> before = ArgumentCaptor.forClass(Map.class);
        ArgumentCaptor<Map<String, Object>> after = ArgumentCaptor.forClass(Map.class);
        verify(audit).record(eq("team.member_joined"), eq("team_member"), eq("3/7"), eq(3),
            before.capture(), after.capture());
        assertThat(before.getValue()).containsEntry("member", false);
        assertThat(after.getValue()).containsEntry("member", true).containsEntry("is_owner", true)
            .containsEntry("source", "MANUAL");
    }

    @Test
    @SuppressWarnings("unchecked")
    void leavingATeamRecordsWhatWasLost() {
        when(members.findById(new TeamMemberId(7, 3)))
            .thenReturn(Optional.of(member(7, 3, true, TeamMemberSource.MANUAL)));

        service.leave(7, 3);

        ArgumentCaptor<Map<String, Object>> before = ArgumentCaptor.forClass(Map.class);
        verify(audit).record(eq("team.member_removed"), eq("team_member"), eq("3/7"), eq(3),
            before.capture(), any());
        assertThat(before.getValue()).containsEntry("is_owner", true);
    }

    @Test
    void revokingOwnershipNamesTheTeam() {
        when(members.findById_UserId(7)).thenReturn(List.of(member(7, 3, true, TeamMemberSource.MANUAL),
            member(7, 4, false, TeamMemberSource.MANUAL)));

        service.revokeOwnerships(7);

        verify(audit).record(eq("team.ownership_revoked"), eq("team_member"), eq("3/7"), eq(3), any(), any());
    }
}
