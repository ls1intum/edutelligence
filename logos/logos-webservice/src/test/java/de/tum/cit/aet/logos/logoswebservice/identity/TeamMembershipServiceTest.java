package de.tum.cit.aet.logos.logoswebservice.identity;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import org.mockito.junit.jupiter.MockitoExtension;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMember;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberId;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberSource;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.service.ApiKeyFactory;
import de.tum.cit.aet.logos.logoswebservice.identity.service.TeamMembershipService;

@ExtendWith(MockitoExtension.class)
class TeamMembershipServiceTest {

    @Mock TeamMemberRepository memberRepository;
    @Mock ApiKeyRepository apiKeyRepository;
    @Mock UserRepository userRepository;
    @Mock TeamRepository teamRepository;
    @Mock ApiKeyFactory apiKeyFactory;
    @InjectMocks TeamMembershipService service;

    private User user;
    private Team team;

    @BeforeEach
    void setUp() {
        user = new User();
        user.setUsername("alice");
        user.setPrename("Alice");
        user.setName("Doe");
        user.setRole("app_developer");

        team = new Team();
        team.setName("artemis");
    }

    private void stubUserAndTeam() {
        when(userRepository.findById(1)).thenReturn(Optional.of(user));
        when(teamRepository.findById(10)).thenReturn(Optional.of(team));
    }

    private static ApiKey developerKey(String keyValue) {
        ApiKey key = new ApiKey();
        key.setKeyValue(keyValue);
        key.setKeyType(ApiKeyType.developer);
        key.setIsActive(false);
        return key;
    }

    @Test
    void join_createsMembershipWithSourceAndDeveloperKey() {
        when(memberRepository.findById(any())).thenReturn(Optional.empty());
        when(userRepository.findById(any())).thenReturn(Optional.of(user));
        when(teamRepository.findById(any())).thenReturn(Optional.of(team));
        when(apiKeyRepository.findByUserIdAndTeamIdAndKeyType(any(), any(), eq(ApiKeyType.developer)))
            .thenReturn(List.of());

        ApiKey fakeKey = new ApiKey();
        fakeKey.setKeyValue("lg-artemis-alice-randomvalue");
        when(apiKeyFactory.createDeveloperKey(user, team)).thenReturn(fakeKey);

        Optional<String> result = service.join(1, 10, false, TeamMemberSource.MANUAL);

        assertThat(result).isPresent().contains("lg-artemis-alice-randomvalue");
        verify(apiKeyRepository).save(fakeKey);

        ArgumentCaptor<TeamMember> memberCaptor = ArgumentCaptor.forClass(TeamMember.class);
        verify(memberRepository).save(memberCaptor.capture());
        assertThat(memberCaptor.getValue().getSource()).isEqualTo(TeamMemberSource.MANUAL);
    }

    @Test
    void leave_removesMembershipAndDeactivatesKey() {
        ApiKey activeKey = new ApiKey();
        activeKey.setKeyValue("lg-artemis-alice-abc");
        activeKey.setIsActive(true);

        when(apiKeyRepository.findByUserIdAndTeamIdAndKeyType(1, 10, ApiKeyType.developer))
            .thenReturn(List.of(activeKey));

        service.leave(1, 10);

        verify(memberRepository).deleteById(new TeamMemberId(1, 10));
        assertThat(activeKey.getIsActive()).isFalse();
        verify(apiKeyRepository).save(activeKey);
    }

    @Test
    void rejoin_reactivatesExistingKeyInsteadOfCreatingNew() {
        when(memberRepository.findById(any())).thenReturn(Optional.empty());
        when(userRepository.findById(any())).thenReturn(Optional.of(user));
        when(teamRepository.findById(any())).thenReturn(Optional.of(team));

        ApiKey inactiveKey = new ApiKey();
        inactiveKey.setKeyValue("lg-artemis-alice-old");
        inactiveKey.setIsActive(false);

        when(apiKeyRepository.findByUserIdAndTeamIdAndKeyType(any(), any(), eq(ApiKeyType.developer)))
            .thenReturn(List.of(inactiveKey));

        Optional<String> result = service.join(1, 10, false, TeamMemberSource.KEYCLOAK);

        assertThat(result).isPresent().contains("lg-artemis-alice-old");
        assertThat(inactiveKey.getIsActive()).isTrue();
        verify(apiKeyFactory, never()).createDeveloperKey(any(), any());
    }

    @Test
    void join_keycloakTakesOverExistingManualMembership() {
        stubUserAndTeam();
        TeamMember manual = new TeamMember();
        manual.setId(new TeamMemberId(1, 10));
        manual.setIsOwner(true);
        manual.setSource(TeamMemberSource.MANUAL);
        ApiKey existingKey = developerKey("lg-artemis-alice-existing");
        when(memberRepository.findById(new TeamMemberId(1, 10))).thenReturn(Optional.of(manual));
        when(apiKeyRepository.findByUserIdAndTeamIdAndKeyType(1, 10, ApiKeyType.developer))
            .thenReturn(List.of(existingKey));

        Optional<String> result = service.join(1, 10, false, TeamMemberSource.KEYCLOAK);

        assertThat(result).isPresent().contains("lg-artemis-alice-existing");
        assertThat(manual.getSource()).isEqualTo(TeamMemberSource.KEYCLOAK);
        assertThat(manual.getIsOwner()).isTrue();
        assertThat(existingKey.getIsActive()).isTrue();
        verify(memberRepository).save(manual);
        verify(apiKeyRepository).save(existingKey);
        verify(apiKeyFactory, never()).createDeveloperKey(any(), any());
    }

    @Test
    void join_manualDoesNotDowngradeExistingKeycloakMembership() {
        stubUserAndTeam();
        TeamMember keycloak = new TeamMember();
        keycloak.setId(new TeamMemberId(1, 10));
        keycloak.setIsOwner(false);
        keycloak.setSource(TeamMemberSource.KEYCLOAK);
        ApiKey existingKey = developerKey("lg-artemis-alice-existing");
        when(memberRepository.findById(new TeamMemberId(1, 10))).thenReturn(Optional.of(keycloak));
        when(apiKeyRepository.findByUserIdAndTeamIdAndKeyType(1, 10, ApiKeyType.developer))
            .thenReturn(List.of(existingKey));

        Optional<String> result = service.join(1, 10, false, TeamMemberSource.MANUAL);

        assertThat(result).isPresent().contains("lg-artemis-alice-existing");
        assertThat(keycloak.getSource()).isEqualTo(TeamMemberSource.KEYCLOAK);
        assertThat(existingKey.getIsActive()).isTrue();
        verify(memberRepository).save(keycloak);
        verify(apiKeyRepository).save(existingKey);
        verify(apiKeyFactory, never()).createDeveloperKey(any(), any());
    }
}
