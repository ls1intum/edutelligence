package de.tum.cit.aet.logos.logoswebservice.identity;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakClaims;
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
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakUserSyncService;

@SpringBootTest
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
        "spring.liquibase.enabled=true",
        "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
        "logos.auth.roles.logos-admin=itg-admin",
        "logos.auth.roles.app-admin=chair-member",
        "logos.auth.sync-debounce-minutes=5",
        "logos.auth.auto-provision-teams=true"
})
@Sql(scripts = "/sql/seed-identity.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = "/sql/cleanup-identity.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class KeycloakUserSyncServiceTest {

    @Autowired KeycloakUserSyncService syncService;
    @Autowired UserRepository userRepository;
    @MockitoBean JwtDecoder jwtDecoder;
    @Autowired TeamRepository teamRepository;
    @Autowired TeamMemberRepository memberRepository;
    @Autowired ApiKeyRepository apiKeyRepository;

    private static final String NEW_SUB = "33333333-3333-3333-3333-333333333333";

    private KeycloakClaims claims(String sub, String username, Set<String> roles) {
        return new KeycloakClaims(sub, username, "Pre", "Name", username + "@tum.de", roles, null);
    }

    private Team linkTeamToGroup(String group) {
        Team team = teamRepository.findById(2001).orElseThrow();
        team.setKeycloakGroup(group);
        return teamRepository.save(team);
    }

    @Test
    void firstLogin_withNoRoles_registersUserAndCreatesNoKeys() {
        User user = syncService.syncFromClaims(claims(NEW_SUB, "newbie", Set.of()));

        assertThat(user.getId()).isNotNull();
        assertThat(user.getKeycloakId()).isEqualTo(UUID.fromString(NEW_SUB));
        assertThat(user.getRole()).isEqualTo("app_developer");
        assertThat(user.getIsActive()).isTrue();
        assertThat(user.getLastSyncedAt()).isNotNull();
        assertThat(apiKeyRepository.findByUserId(user.getId())).isEmpty();
        apiKeyRepository.findByUserId(user.getId()).forEach(apiKeyRepository::delete);
        userRepository.delete(user);
    }

    @Test
    void firstLogin_withUnknownTeamRole_autoCreatesTeamAndAddsMember() {
        User user = syncService.syncFromClaims(claims(NEW_SUB, "newbie", Set.of("new-project-dev")));

        var autoTeam = teamRepository.findByKeycloakGroup("new-project-dev");
        assertThat(autoTeam).isPresent();
        assertThat(autoTeam.get().getName()).isEqualTo("New Project");
        assertThat(memberRepository.findById(new TeamMemberId(user.getId(), autoTeam.get().getId()))).isPresent();

        memberRepository.findById_TeamId(autoTeam.get().getId()).forEach(memberRepository::delete);
        apiKeyRepository.findByUserId(user.getId()).forEach(apiKeyRepository::delete);
        teamRepository.delete(autoTeam.get());
        userRepository.delete(user);
    }

    @Test
    void deriveTeamName_stripsKnownSuffixesAndTitleCases() {
        var suffixes = java.util.List.of("-dev", "-team", "-group", "-member");
        assertThat(KeycloakUserSyncService.deriveTeamName("artemis-dev", suffixes)).isEqualTo("Artemis");
        assertThat(KeycloakUserSyncService.deriveTeamName("my-cool-project-dev", suffixes)).isEqualTo("My Cool Project");
        assertThat(KeycloakUserSyncService.deriveTeamName("foo-team", suffixes)).isEqualTo("Foo");
        assertThat(KeycloakUserSyncService.deriveTeamName("foo-group", suffixes)).isEqualTo("Foo");
        assertThat(KeycloakUserSyncService.deriveTeamName("foo-bar", suffixes)).isEqualTo("Foo Bar");
        assertThat(KeycloakUserSyncService.deriveTeamName("somegroup", suffixes)).isEqualTo("Somegroup");
    }

    @Test
    void claimMatchingLinkedTeam_createsKeycloakMembershipAndKey() {
        linkTeamToGroup("artemis-dev");
        User user = syncService.syncFromClaims(claims(NEW_SUB, "newbie", Set.of("artemis-dev")));

        TeamMember m = memberRepository.findById(new TeamMemberId(user.getId(), 2001)).orElseThrow();
        assertThat(m.getSource()).isEqualTo(TeamMemberSource.KEYCLOAK);
        assertThat(apiKeyRepository.findByUserIdAndTeamIdAndKeyType(user.getId(), 2001, ApiKeyType.developer))
            .hasSize(1);
        memberRepository.delete(m);
        apiKeyRepository.findByUserId(user.getId()).forEach(apiKeyRepository::delete);
        userRepository.delete(user);
    }

    @Test
    void removedClaim_removesOnlyKeycloakMemberships() {
        linkTeamToGroup("artemis-dev");
        User user = syncService.syncFromClaims(claims(NEW_SUB, "newbie", Set.of("artemis-dev")));
        syncService.syncFromClaims(claims(NEW_SUB, "newbie", Set.of()));

        assertThat(memberRepository.findById(new TeamMemberId(user.getId(), 2001))).isEmpty();
        assertThat(memberRepository.findById(new TeamMemberId(1001, 2001))).isPresent();
        apiKeyRepository.findByUserId(user.getId()).forEach(apiKeyRepository::delete);
        userRepository.delete(userRepository.findById(user.getId()).orElseThrow());
    }

    @Test
    void logosAdminRole_ensuresPersonalKey_lossDeactivatesIt() {
        User user = syncService.syncFromClaims(claims(NEW_SUB, "newbie", Set.of("itg-admin")));
        assertThat(user.getRole()).isEqualTo("logos_admin");
        var personal = apiKeyRepository.findByUserIdAndTeamIdIsNullAndKeyType(user.getId(), ApiKeyType.developer);
        assertThat(personal).hasSize(1);
        assertThat(personal.get(0).getIsActive()).isTrue();

        syncService.syncFromClaims(claims(NEW_SUB, "newbie", Set.of()));
        personal = apiKeyRepository.findByUserIdAndTeamIdIsNullAndKeyType(user.getId(), ApiKeyType.developer);
        assertThat(personal).hasSize(1);
        assertThat(personal.get(0).getIsActive()).isFalse();

        apiKeyRepository.findByUserId(user.getId()).forEach(apiKeyRepository::delete);
        userRepository.delete(userRepository.findById(user.getId()).orElseThrow());
    }

    @Test
    void existingUserMatchedByEmail_getsLinkedToKeycloakId() {
        User user = syncService.syncFromClaims(
            new KeycloakClaims(NEW_SUB, "unknown-username", "P", "N", "admin@test.com", Set.of(), null));
        assertThat(user.getId()).isEqualTo(1002);
        assertThat(user.getKeycloakId()).isEqualTo(UUID.fromString(NEW_SUB));
    }

    @Test
    void syncIfStale_skipsWhenRecentlySynced() {
        User seeded = userRepository.findById(1001).orElseThrow();
        Instant before = seeded.getLastSyncedAt();
        User result = syncService.syncIfStale(
            claims(seeded.getKeycloakId().toString(), "testuser", Set.of("itg-admin")));
        assertThat(result.getRole()).isEqualTo("app_developer");
        assertThat(result.getLastSyncedAt()).isEqualTo(before);
    }

    @Test
    void deactivateUser_disablesUserAndAllKeys() {
        User seeded = userRepository.findById(1001).orElseThrow();
        syncService.deactivateUser(seeded);
        assertThat(userRepository.findById(1001).orElseThrow().getIsActive()).isFalse();
        assertThat(apiKeyRepository.findById(3001).orElseThrow().getIsActive()).isFalse();
    }

    @Test
    void firstLogin_withBuiltinKeycloakRoles_createsNoTeamOrKey() {
        User user = syncService.syncFromClaims(
            claims(NEW_SUB, "newbie", Set.of("offline_access", "uma_authorization", "default-roles-tum")));

        assertThat(teamRepository.findByKeycloakGroup("offline_access")).isEmpty();
        assertThat(teamRepository.findByKeycloakGroup("uma_authorization")).isEmpty();
        assertThat(teamRepository.findByKeycloakGroup("default-roles-tum")).isEmpty();
        assertThat(memberRepository.findById_UserIdAndSource(user.getId(), TeamMemberSource.KEYCLOAK)).isEmpty();
        assertThat(apiKeyRepository.findByUserId(user.getId())).isEmpty();

        userRepository.delete(user);
    }

    @Test
    void manualMembershipMatchingClaim_isTakenOverByKeycloakSync() {
        linkTeamToGroup("artemis-dev");
        User u1001 = userRepository.findById(1001).orElseThrow();
        syncService.syncFromClaims(
            claims(u1001.getKeycloakId().toString(), "testuser", Set.of("artemis-dev")));

        TeamMember m = memberRepository.findById(new TeamMemberId(1001, 2001)).orElseThrow();
        assertThat(m.getSource()).isEqualTo(TeamMemberSource.KEYCLOAK);
    }
}
