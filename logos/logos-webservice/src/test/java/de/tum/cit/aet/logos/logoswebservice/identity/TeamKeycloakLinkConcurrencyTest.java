package de.tum.cit.aet.logos.logoswebservice.identity;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.TimeUnit;

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
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
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
                    42, null, null, null, null, null)));
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

        CompletableFuture<Void> unlinkHoldingTheRow = CompletableFuture.runAsync(() ->
            new TransactionTemplate(txManager).executeWithoutResult(status -> {
                teamRepository.findByIdForUpdate(TEAM_ID).orElseThrow();
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
        assertThat(awaitLockWait())
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

    /** Waits for a backend to block on a lock — the login running into the held team row. */
    private boolean awaitLockWait() throws InterruptedException {
        for (int attempt = 0; attempt < 100; attempt++) {
            Integer waiting = jdbc.queryForObject(
                "SELECT COUNT(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock'", Integer.class);
            if (waiting != null && waiting > 0) return true;
            TimeUnit.MILLISECONDS.sleep(100);
        }
        return false;
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
