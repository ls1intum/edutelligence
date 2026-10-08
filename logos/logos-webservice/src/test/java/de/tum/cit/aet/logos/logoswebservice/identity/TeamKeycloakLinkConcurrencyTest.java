package de.tum.cit.aet.logos.logoswebservice.identity;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakClaims;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateTeamRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakUserSyncService;
import de.tum.cit.aet.logos.logoswebservice.identity.service.TeamService;

/**
 * What must still hold when a Keycloak link is removed while something else is
 * touching the same team.
 *
 * <p>Both cases below pass trivially when the two operations happen to run in
 * sequence, so each runs them against a barrier, repeatedly: the point is that
 * no interleaving can leave the link, or a membership it granted, behind.
 */
@SpringBootTest
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    "logos.auth.roles.logos-admin=itg-admin",
    "logos.auth.roles.app-admin=chair-member",
    "logos.auth.auto-provision-teams=false"
})
@Sql(scripts = "/sql/seed-identity.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = "/sql/cleanup-identity.sql", executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class TeamKeycloakLinkConcurrencyTest {

    private static final int TEAM_ID = 2002;
    private static final String GROUP = "kc-team-group";
    private static final int ROUNDS = 15;

    @Autowired TeamService teamService;
    @Autowired KeycloakUserSyncService syncService;
    @Autowired TeamRepository teamRepository;
    @Autowired UserRepository userRepository;
    @Autowired JdbcTemplate jdbc;
    @Autowired PlatformTransactionManager txManager;

    /**
     * The limits endpoint writes the whole team row, so a save that read the
     * team before the link was removed would put the link back — handing an
     * app_admin owner an unlink-undo they are not allowed to make, and leaving
     * a linked team whose membership cleanup has already run.
     */
    @Test
    void aConcurrentLimitsSaveNeverRestoresARemovedLink() throws Exception {
        for (int round = 0; round < ROUNDS; round++) {
            relink();
            CyclicBarrier start = new CyclicBarrier(2);

            CompletableFuture<Void> unlink = run(start, () ->
                teamService.updateTeamKeycloakGroup(TEAM_ID, null));
            CompletableFuture<Void> limits = run(start, () ->
                teamService.updateTeamLimits(TEAM_ID, new UpdateTeamRequestDTO(
                    42, null, null, null, null, null, null)));
            CompletableFuture.allOf(unlink, limits).join();

            assertThat(storedGroup())
                .as("round %d: the link must stay removed", round)
                .isNull();
        }
    }

    /**
     * A login resolves its teams and then joins them, so a link removed in
     * between could still produce a membership (and re-activate the developer
     * key that comes with it) for a team the user no longer belongs to.
     *
     * <p>Holding the team row for the rest of the login closes that window.
     * The removal here runs inside the transaction that holds the lock, which
     * is what an unlink arriving mid-login does: the login has to wait for it,
     * and then sees no link at all. Without the lock the login sails past the
     * held row and the first assertion fails.
     */
    @Test
    void aLoginInFlightNeverJoinsThroughARemovedLink() throws Exception {
        relink();
        UUID subject = UUID.randomUUID();
        CountDownLatch locked = new CountDownLatch(1);
        CountDownLatch unlinked = new CountDownLatch(1);

        AtomicInteger holder = new AtomicInteger();
        CompletableFuture<Void> unlinkHoldingTheRow = CompletableFuture.runAsync(() ->
            new TransactionTemplate(txManager).executeWithoutResult(status -> {
                teamRepository.findByIdForUpdate(TEAM_ID).orElseThrow();
                holder.set(backendPid());
                locked.countDown();
                try {
                    // Let the login run into the held row before committing.
                    unlinked.await(10, TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                teamService.updateTeamKeycloakGroup(TEAM_ID, null);
            }));

        assertThat(locked.await(10, TimeUnit.SECONDS)).isTrue();
        CompletableFuture<Void> login = CompletableFuture.runAsync(() -> syncService.syncFromClaims(
            new KeycloakClaims(subject.toString(), "racer", "Race", "User",
                subject + "@test.com", Set.of(GROUP), Instant.now())));

        // Release the unlink only once the login is genuinely stuck on the held
        // row; counting down earlier would let the unlink finish first and the
        // interleaving under test would never happen.
        assertThat(awaitBlockedBy(holder.get()))
            .as("the login must reach the held team row")
            .isTrue();
        assertThat(login).isNotCompleted();
        unlinked.countDown();
        CompletableFuture.allOf(unlinkHoldingTheRow, login).get(30, TimeUnit.SECONDS);

        assertThat(storedGroup()).isNull();
        assertThat(membershipsOf(subject))
            .as("no membership may survive the unlink")
            .isZero();
    }

    /**
     * Re-enabling an account switches its keys back on, skipping any key whose
     * team the user is no longer in. That check is a read, and unlinking the
     * team is what deletes the membership it reads — so the two have to be
     * serialized. If the login could check membership, then let the unlink
     * commit, then switch the key on, nothing afterwards would take it away:
     * the reconciliation that follows finds no link to the team and no
     * membership left to remove, and the gateway honours the key without ever
     * consulting team_members.
     *
     * <p>Holding every team named by the user's keys for the rest of the login
     * closes that window, the same way the join path is closed above.
     */
    @Test
    void aReEnabledLoginNeverRevivesAKeyTheUnlinkIsRemoving() throws Exception {
        relink();
        UUID subject = UUID.randomUUID();
        // A Keycloak-synced member holding the team's developer key, then
        // switched off in Keycloak — which switches the key off with them.
        User member = syncService.syncFromClaims(claims(subject));
        syncService.deactivateUser(userRepository.findById(member.getId()).orElseThrow());
        Integer keyId = jdbc.queryForObject(
            "SELECT id FROM api_keys WHERE user_id = ? AND team_id = ?",
            Integer.class, member.getId(), TEAM_ID);
        assertThat(keyIsActive(keyId)).isFalse();

        CountDownLatch locked = new CountDownLatch(1);
        CountDownLatch unlinked = new CountDownLatch(1);
        AtomicInteger holder = new AtomicInteger();

        CompletableFuture<Void> unlinkHoldingTheRow = CompletableFuture.runAsync(() ->
            new TransactionTemplate(txManager).executeWithoutResult(status -> {
                teamRepository.findByIdForUpdate(TEAM_ID).orElseThrow();
                holder.set(backendPid());
                locked.countDown();
                try {
                    // Let the login run into the held row before committing.
                    unlinked.await(10, TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                teamService.updateTeamKeycloakGroup(TEAM_ID, null);
            }));

        assertThat(locked.await(10, TimeUnit.SECONDS)).isTrue();
        // Keycloak re-enables the account.
        CompletableFuture<Void> login =
            CompletableFuture.runAsync(() -> syncService.syncFromClaims(claims(subject)));

        assertThat(awaitBlockedBy(holder.get()))
            .as("the login must reach the held team row before it touches that team's keys")
            .isTrue();
        assertThat(login).isNotCompleted();
        unlinked.countDown();
        CompletableFuture.allOf(unlinkHoldingTheRow, login).get(30, TimeUnit.SECONDS);

        assertThat(storedGroup()).isNull();
        assertThat(membershipsOf(subject))
            .as("no membership may survive the unlink")
            .isZero();
        assertThat(keyIsActive(keyId))
            .as("the key of a team the login no longer belongs to must stay off")
            .isFalse();
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

    private KeycloakClaims claims(UUID subject) {
        return new KeycloakClaims(subject.toString(), "racer", "Race", "User",
            subject + "@test.com", Set.of(GROUP), Instant.now());
    }

    private Boolean keyIsActive(Integer keyId) {
        return jdbc.queryForObject("SELECT is_active FROM api_keys WHERE id = ?", Boolean.class, keyId);
    }

    private Integer membershipsOf(UUID subject) {
        return jdbc.queryForObject("""
            SELECT COUNT(*) FROM team_members tm
            JOIN users u ON u.id = tm.user_id
            WHERE tm.team_id = ? AND u.keycloak_id = ?
            """, Integer.class, TEAM_ID, subject);
    }

    private void relink() {
        jdbc.update("UPDATE teams SET keycloak_group = ? WHERE id = ?", GROUP, TEAM_ID);
    }

    private String storedGroup() {
        return jdbc.queryForObject("SELECT keycloak_group FROM teams WHERE id = ?", String.class, TEAM_ID);
    }

    private static CompletableFuture<Void> run(CyclicBarrier start, Runnable action) {
        return CompletableFuture.runAsync(() -> {
            try {
                start.await();
            } catch (Exception e) {
                throw new IllegalStateException(e);
            }
            action.run();
        });
    }
}
