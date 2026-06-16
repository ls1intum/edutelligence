package de.tum.cit.aet.logos.logoswebservice.identity;

import java.util.Set;

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
        "logos.auth.roles.app-admin=chair-member"
})
@Sql(scripts = "/sql/seed-identity.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = "/sql/cleanup-identity.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class KeycloakAutoProvisionDisabledTest {

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

    @Test
    void unknownTeamRole_doesNotAutoCreateTeamOrKey() {
        User user = syncService.syncFromClaims(claims(NEW_SUB, "newbie", Set.of("new-project-dev")));

        assertThat(teamRepository.findByKeycloakGroup("new-project-dev")).isEmpty();
        assertThat(memberRepository.findById_UserIdAndSource(user.getId(), TeamMemberSource.KEYCLOAK)).isEmpty();
        assertThat(apiKeyRepository.findByUserId(user.getId())).isEmpty();

        userRepository.delete(user);
    }

    @Test
    void adminLinkedTeam_isStillJoined() {
        Team team = teamRepository.findById(2001).orElseThrow();
        team.setKeycloakGroup("artemis-dev");
        teamRepository.save(team);

        User user = syncService.syncFromClaims(claims(NEW_SUB, "newbie", Set.of("artemis-dev")));

        TeamMember m = memberRepository.findById(new TeamMemberId(user.getId(), 2001)).orElseThrow();
        assertThat(m.getSource()).isEqualTo(TeamMemberSource.KEYCLOAK);
        assertThat(apiKeyRepository.findByUserIdAndTeamIdAndKeyType(user.getId(), 2001, ApiKeyType.developer))
            .hasSize(1);

        memberRepository.delete(m);
        apiKeyRepository.findByUserId(user.getId()).forEach(apiKeyRepository::delete);
        userRepository.delete(user);
    }
}
