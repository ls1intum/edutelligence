package de.tum.cit.aet.logos.logoswebservice.identity;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakClaims;
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
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakUserSyncService;
import de.tum.cit.aet.logos.logoswebservice.identity.service.TeamService;

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
    @Autowired ApiKeyFactory apiKeyFactory;
    @Autowired TeamService teamService;
    @Autowired JdbcTemplate jdbc;
    @Autowired PlatformTransactionManager txManager;

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
        assertThat(user.isActive()).isTrue();
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
    void logosAdminRole_doesNotMintPersonalKey_andDeactivatesExistingOnes() {
        User user = syncService.syncFromClaims(claims(NEW_SUB, "newbie", Set.of("itg-admin")));
        assertThat(user.getRole()).isEqualTo("logos_admin");

        // Admins no longer receive an auto-provisioned team-less "master" key;
        // they obtain keys through team membership like every other user.
        assertThat(apiKeyRepository.findByUserIdAndTeamIdIsNullAndKeyType(user.getId(), ApiKeyType.developer))
            .isEmpty();

        // Any pre-existing team-less developer key is deactivated on next sync.
        ApiKey legacy = apiKeyFactory.createDeveloperKey(user, null);
        legacy.setIsActive(true);
        apiKeyRepository.save(legacy);

        syncService.syncFromClaims(claims(NEW_SUB, "newbie", Set.of("itg-admin")));
        var personal = apiKeyRepository.findByUserIdAndTeamIdIsNullAndKeyType(user.getId(), ApiKeyType.developer);
        assertThat(personal).hasSize(1);
        assertThat(personal.get(0).getIsActive()).isFalse();

        apiKeyRepository.findByUserId(user.getId()).forEach(apiKeyRepository::delete);
        userRepository.delete(userRepository.findById(user.getId()).orElseThrow());
    }

    @Test
    void existingUserMatchedByEmail_getsLinkedToKeycloakId() {
        User existing = new User();
        existing.setUsername("legacyadmin");
        existing.setPrename("Legacy");
        existing.setName("Admin");
        existing.setRole("app_developer");
        existing.setEmail("legacy-admin@test.com");
        existing = userRepository.saveAndFlush(existing);

        try {
            User user = syncService.syncFromClaims(
                new KeycloakClaims(NEW_SUB, "unknown-username", "P", "N", "legacy-admin@test.com", Set.of(), null));
            assertThat(user.getId()).isEqualTo(existing.getId());
            assertThat(user.getKeycloakId()).isEqualTo(UUID.fromString(NEW_SUB));
        } finally {
            userRepository.findByKeycloakId(UUID.fromString(NEW_SUB)).ifPresent(userRepository::delete);
            userRepository.findById(existing.getId()).ifPresent(userRepository::delete);
        }
    }

    @Test
    void existingUserWithDifferentKeycloakId_throwsConflictInsteadOfDuplicateEmail() {
        User existing = new User();
        existing.setUsername("recreated");
        existing.setPrename("Re");
        existing.setName("Created");
        existing.setRole("app_developer");
        existing.setEmail("recreated@test.com");
        existing.setKeycloakId(UUID.fromString("11111111-1111-1111-1111-111111111111"));
        existing = userRepository.saveAndFlush(existing);

        try {
            org.junit.jupiter.api.Assertions.assertThrows(
                de.tum.cit.aet.logos.logoswebservice.common.ConflictException.class,
                () -> syncService.syncFromClaims(
                    new KeycloakClaims(NEW_SUB, "recreated", "Re", "Created", "recreated@test.com", Set.of(), null)));
            // The login subject must not have been inserted as a second row.
            assertThat(userRepository.findByKeycloakId(UUID.fromString(NEW_SUB))).isEmpty();
        } finally {
            userRepository.findById(existing.getId()).ifPresent(userRepository::delete);
        }
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
        assertThat(userRepository.findById(1001).orElseThrow().isActive()).isFalse();
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
    void syncDemotingOwnerToDeveloper_revokesOwnershipButKeepsMembership() {
        // adminuser (1002) owns team 2001; Keycloak no longer reports an admin role.
        User u1002 = userRepository.findById(1002).orElseThrow();
        User synced = syncService.syncFromClaims(
            claims(u1002.getKeycloakId().toString(), "adminuser", Set.of()));

        assertThat(synced.getRole()).isEqualTo("app_developer");
        TeamMember m = memberRepository.findById(new TeamMemberId(1002, 2001)).orElseThrow();
        assertThat(m.getIsOwner()).isFalse();
    }

    @Test
    void syncKeepingAdminRole_keepsOwnership() {
        User u1002 = userRepository.findById(1002).orElseThrow();
        User synced = syncService.syncFromClaims(
            claims(u1002.getKeycloakId().toString(), "adminuser", Set.of("chair-member")));

        assertThat(synced.getRole()).isEqualTo("app_admin");
        TeamMember m = memberRepository.findById(new TeamMemberId(1002, 2001)).orElseThrow();
        assertThat(m.getIsOwner()).isTrue();
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

    /**
     * A key carries its team's permissions and budget and the inference path
     * never re-checks membership, so the key of a team the user was removed
     * from while deactivated must not come back when Keycloak re-enables them.
     * Unlinking the team is one way to produce exactly that state.
     */
    @Test
    void reEnabledUser_doesNotRegainTheKeyOfATeamTheyWereRemovedFrom() {
        Team team = linkTeamToGroup("kc-synced");
        User member = syncService.syncFromClaims(claims(NEW_SUB, "synced", Set.of("kc-synced")));
        ApiKey teamKey = apiKeyRepository
            .findByUserIdAndTeamIdAndKeyType(member.getId(), team.getId(), ApiKeyType.developer)
            .getFirst();
        assertThat(teamKey.getIsActive()).isTrue();

        // Keycloak disables the account, and the team is unlinked while it is
        // off — which drops the membership and switches the key off with it.
        syncService.deactivateUser(userRepository.findById(member.getId()).orElseThrow());
        teamService.updateTeamKeycloakGroup(team.getId(), null);
        assertThat(memberRepository.findById(new TeamMemberId(member.getId(), team.getId()))).isEmpty();

        // The account comes back. The key must not.
        syncService.syncFromClaims(claims(NEW_SUB, "synced", Set.of("kc-synced")));

        assertThat(apiKeyRepository.findById(teamKey.getId()).orElseThrow().getIsActive())
            .as("a key for a team the user is no longer in must stay inactive")
            .isFalse();
    }

    @Test
    void reEnabledUser_regainsTheKeyOfATeamTheyAreStillIn() {
        Team team = linkTeamToGroup("kc-synced");
        User member = syncService.syncFromClaims(claims(NEW_SUB, "synced", Set.of("kc-synced")));
        ApiKey teamKey = apiKeyRepository
            .findByUserIdAndTeamIdAndKeyType(member.getId(), team.getId(), ApiKeyType.developer)
            .getFirst();

        syncService.deactivateUser(userRepository.findById(member.getId()).orElseThrow());
        assertThat(apiKeyRepository.findById(teamKey.getId()).orElseThrow().getIsActive()).isFalse();

        syncService.syncFromClaims(claims(NEW_SUB, "synced", Set.of("kc-synced")));

        assertThat(apiKeyRepository.findById(teamKey.getId()).orElseThrow().getIsActive()).isTrue();
    }

    /**
     * Auto-provisioning adopts a same-named unlinked team rather than creating
     * a duplicate, which makes it a second writer of {@code keycloak_group}. It
     * has to lose against an admin who links that team first: read, check and
     * save would overwrite the committed link with the derived one, and the
     * login would then join through a link nobody chose.
     */
    @Test
    void adoption_neverOverwritesALinkCommittedWhileItWaited() throws Exception {
        Integer adoptable = jdbc.queryForObject(
            "INSERT INTO teams (name) VALUES ('Foo') RETURNING id", Integer.class);
        UUID subject = UUID.randomUUID();
        CountDownLatch locked = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        AtomicInteger holder = new AtomicInteger();
        try {
            CompletableFuture<Void> adminLink = CompletableFuture.runAsync(() ->
                new TransactionTemplate(txManager).executeWithoutResult(status -> {
                    teamService.updateTeamKeycloakGroup(adoptable, "bar-dev");
                    holder.set(backendPid());
                    locked.countDown();
                    try {
                        // Hold the row so the adoption runs into it before committing.
                        release.await(10, TimeUnit.SECONDS);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    }
                }));

            assertThat(locked.await(10, TimeUnit.SECONDS)).isTrue();
            CompletableFuture<Void> login = CompletableFuture.runAsync(() ->
                syncService.syncFromClaims(new KeycloakClaims(subject.toString(), "adopter",
                    "Ad", "Opter", subject + "@tum.de", Set.of("foo-dev"), Instant.now())));

            assertThat(awaitBlockedBy(holder.get()))
                .as("the adoption must reach the held team row").isTrue();
            release.countDown();
            CompletableFuture.allOf(adminLink, login).get(30, TimeUnit.SECONDS);

            assertThat(teamRepository.findById(adoptable).orElseThrow().getKeycloakGroup())
                .as("the admin's link stands")
                .isEqualTo("bar-dev");
            assertThat(teamRepository.findByKeycloakGroup("foo-dev"))
                .as("the adoption falls back to a team of its own")
                .get()
                .extracting(Team::getId)
                .isNotEqualTo(adoptable);
        } finally {
            release.countDown();
            jdbc.update("""
                DELETE FROM api_keys WHERE team_id IN (
                    SELECT id FROM teams WHERE name = 'Foo' OR keycloak_group IN ('foo-dev', 'bar-dev'))
                """);
            jdbc.update("""
                DELETE FROM team_members WHERE team_id IN (
                    SELECT id FROM teams WHERE name = 'Foo' OR keycloak_group IN ('foo-dev', 'bar-dev'))
                """);
            jdbc.update("DELETE FROM teams WHERE name = 'Foo' OR keycloak_group IN ('foo-dev', 'bar-dev')");
        }
    }

    /**
     * The name is the only reason adoption picks a particular team, so a rename
     * committed while the adoption waits invalidates the choice. Claiming the
     * team anyway would pour the group's members into a team that no longer
     * answers to the group's derived name — and hand them its budget.
     */
    @Test
    void adoption_neverClaimsATeamRenamedWhileItWaited() throws Exception {
        Integer adoptable = jdbc.queryForObject(
            "INSERT INTO teams (name) VALUES ('Foo') RETURNING id", Integer.class);
        UUID subject = UUID.randomUUID();
        CountDownLatch locked = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        AtomicInteger holder = new AtomicInteger();
        try {
            CompletableFuture<Void> adminRename = CompletableFuture.runAsync(() ->
                new TransactionTemplate(txManager).executeWithoutResult(status -> {
                    teamService.updateTeamName(adoptable, "Bar");
                    holder.set(backendPid());
                    locked.countDown();
                    try {
                        // Hold the row so the adoption runs into it before committing.
                        release.await(10, TimeUnit.SECONDS);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    }
                }));

            assertThat(locked.await(10, TimeUnit.SECONDS)).isTrue();
            // The login still sees the committed name 'Foo', so it picks this
            // team to adopt and then blocks on the row the rename holds.
            CompletableFuture<Void> login = CompletableFuture.runAsync(() ->
                syncService.syncFromClaims(new KeycloakClaims(subject.toString(), "adopter",
                    "Ad", "Opter", subject + "@tum.de", Set.of("foo-dev"), Instant.now())));

            assertThat(awaitBlockedBy(holder.get()))
                .as("the adoption must reach the held team row").isTrue();
            release.countDown();
            CompletableFuture.allOf(adminRename, login).get(30, TimeUnit.SECONDS);

            assertThat(teamRepository.findById(adoptable).orElseThrow())
                .as("the renamed team is not the one 'foo-dev' derives, so it stays unlinked")
                .extracting(Team::getName, Team::getKeycloakGroup)
                .containsExactly("Bar", null);
            assertThat(teamRepository.findByKeycloakGroup("foo-dev"))
                .as("the adoption falls back to a team of its own")
                .get()
                .extracting(Team::getId)
                .isNotEqualTo(adoptable);
        } finally {
            release.countDown();
            jdbc.update("""
                DELETE FROM api_keys WHERE team_id IN (
                    SELECT id FROM teams WHERE name IN ('Foo', 'Bar') OR keycloak_group = 'foo-dev')
                """);
            jdbc.update("""
                DELETE FROM team_members WHERE team_id IN (
                    SELECT id FROM teams WHERE name IN ('Foo', 'Bar') OR keycloak_group = 'foo-dev')
                """);
            jdbc.update("DELETE FROM teams WHERE name IN ('Foo', 'Bar') OR keycloak_group = 'foo-dev'");
        }
    }

    /**
     * Waits until some backend is blocked <em>by the transaction we are holding
     * the row in</em> — not merely until something, somewhere in this database,
     * waits on a lock. A test container is shared, and an unrelated waiter would
     * otherwise release the holder before the contended statement ever reached
     * the row, leaving the assertions to pass without the race having happened.
     * {@code pg_blocking_pids} names the blockers, so we can insist it is ours.
     */
    private boolean awaitBlockedBy(int holderPid) throws InterruptedException {
        for (int attempt = 0; attempt < 100; attempt++) {
            Integer waiting = jdbc.queryForObject("""
                SELECT COUNT(*) FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND pid <> ?
                  AND ? = ANY(pg_blocking_pids(pid))
                """, Integer.class, holderPid, holderPid);
            if (waiting != null && waiting > 0) return true;
            TimeUnit.MILLISECONDS.sleep(100);
        }
        return false;
    }

    /** Backend pid of the current transaction; JdbcTemplate shares its connection. */
    private int backendPid() {
        return jdbc.queryForObject("SELECT pg_backend_pid()", Integer.class);
    }
}
