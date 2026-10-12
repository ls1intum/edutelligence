package de.tum.cit.aet.logos.logoswebservice.identity;

import static org.assertj.core.api.Assertions.assertThat;

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
import de.tum.cit.aet.logos.logoswebservice.identity.entity.TeamMemberId;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.service.KeycloakUserSyncService;
import de.tum.cit.aet.logos.logoswebservice.identity.service.SessionApiKeyService;
import de.tum.cit.aet.logos.logoswebservice.identity.service.TeamMembershipService;

/**
 * What must still hold when a session key is minted in the same moment the
 * owner's account is deactivated, or the owner leaves the key's team.
 *
 * <p>Both deactivation paths enumerate the keys they switch off, and the mint
 * inserts an active child, so whichever commits first decides what the other
 * sees. The two deterministic cases hold the row the deactivation locks first
 * and prove the mint waits for it and is then refused; the barrier cases race
 * the two repeatedly, so no interleaving may leave an active session key
 * behind. Nothing afterwards would notice one it missed: the gateway honours
 * is_active alone, and the orphan janitor only reaps keys of terminal
 * sessions.
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
class SessionApiKeyMintConcurrencyTest {

    private static final int OWNER_ID = 1001;
    private static final int TEAM_ID = 2001;
    private static final int PARENT_KEY_ID = 3001;
    private static final String PARENT_KEY_VALUE = "dev-key-1";
    private static final int ROUNDS = 15;

    @Autowired SessionApiKeyService sessionApiKeyService;
    @Autowired KeycloakUserSyncService syncService;
    @Autowired TeamMembershipService membershipService;
    @Autowired UserRepository userRepository;
    @Autowired TeamMemberRepository teamMemberRepository;
    @Autowired JdbcTemplate jdbc;
    @Autowired PlatformTransactionManager txManager;

    /**
     * Account deactivation locks the owner's row before it sweeps the
     * owner's keys. The mint has to take the same lock before it re-checks
     * the owner, so a deactivation that holds the row refuses the mint
     * instead of committing around it: the sweep would otherwise enumerate
     * before the child is inserted, the mint would commit an active child,
     * and the deactivation would commit without ever seeing it.
     */
    @Test
    void aDeactivationHoldingTheOwnerRowRefusesTheMint() throws Exception {
        CountDownLatch locked = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        AtomicInteger holder = new AtomicInteger();

        CompletableFuture<Void> deactivation = CompletableFuture.runAsync(() ->
            new TransactionTemplate(txManager).executeWithoutResult(status -> {
                userRepository.findByIdForUpdate(OWNER_ID).orElseThrow();
                holder.set(backendPid());
                locked.countDown();
                try {
                    // Let the mint run into the held row before committing.
                    release.await(10, TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                syncService.deactivateUser(userRepository.findById(OWNER_ID).orElseThrow());
            }));

        assertThat(locked.await(10, TimeUnit.SECONDS)).isTrue();
        int sessionId = newSession();
        CompletableFuture<Void> mint = CompletableFuture.runAsync(() ->
            sessionApiKeyService.mint(PARENT_KEY_VALUE, "agent-session-race", sessionId));

        // Release the deactivation only once the mint is genuinely stuck on
        // the held row; counting down earlier would let it finish first and
        // the interleaving under test would never happen.
        assertThat(awaitBlockedBy(holder.get()))
            .as("the mint must reach the held owner row")
            .isTrue();
        assertThat(mint).isNotCompleted();
        release.countDown();
        CompletableFuture.allOf(deactivation, mint).get(30, TimeUnit.SECONDS);
        assertThat(mint.isCompletedExceptionally())
            .as("the mint must be refused once the owner is deactivated")
            .isTrue();

        assertNoSessionKey(PARENT_KEY_ID);
        assertThat(keyIsActive(PARENT_KEY_ID)).isFalse();
        assertThat(ownerIsActive(OWNER_ID)).isFalse();
    }

    /**
     * Leaving the team locks the membership row before it sweeps the team's
     * keys. The mint has to take the same lock before it re-checks the
     * membership, so a leave that holds the row refuses the mint instead of
     * committing around it: the sweep would otherwise enumerate before the
     * child is inserted, the mint would commit an active child, and the leave
     * would commit without ever seeing it — leaving a usable key for a team
     * the user no longer belongs in.
     */
    @Test
    void aLeaveHoldingTheMembershipRowRefusesTheMint() throws Exception {
        CountDownLatch locked = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        AtomicInteger holder = new AtomicInteger();

        CompletableFuture<Void> leave = CompletableFuture.runAsync(() ->
            new TransactionTemplate(txManager).executeWithoutResult(status -> {
                teamMemberRepository
                    .findByIdForUpdate(new TeamMemberId(OWNER_ID, TEAM_ID)).orElseThrow();
                holder.set(backendPid());
                locked.countDown();
                try {
                    // Let the mint run into the held row before committing.
                    release.await(10, TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                membershipService.leave(OWNER_ID, TEAM_ID);
            }));

        assertThat(locked.await(10, TimeUnit.SECONDS)).isTrue();
        int sessionId = newSession();
        CompletableFuture<Void> mint = CompletableFuture.runAsync(() ->
            sessionApiKeyService.mint(PARENT_KEY_VALUE, "agent-session-race", sessionId));

        assertThat(awaitBlockedBy(holder.get()))
            .as("the mint must reach the held membership row")
            .isTrue();
        assertThat(mint).isNotCompleted();
        release.countDown();
        CompletableFuture.allOf(leave, mint).get(30, TimeUnit.SECONDS);
        assertThat(mint.isCompletedExceptionally())
            .as("the mint must be refused once the owner has left the team")
            .isTrue();

        assertNoSessionKey(PARENT_KEY_ID);
        assertThat(keyIsActive(PARENT_KEY_ID)).isFalse();
        assertThat(isMember(OWNER_ID, TEAM_ID)).isFalse();
    }

    /**
     * Run deactivation and mint against a barrier, repeatedly. Whichever
     * wins the owner row decides what the other sees: the mint is refused,
     * or it commits first and the sweep that follows must switch its child
     * off with the rest.
     */
    @Test
    void deactivationRacingAMintLeavesNoActiveSessionKey() throws Exception {
        for (int round = 0; round < ROUNDS; round++) {
            resetRound(false);
            int sessionId = newSession();
            CyclicBarrier start = new CyclicBarrier(2);

            CompletableFuture<Void> deactivation = run(start, () ->
                syncService.deactivateUser(userRepository.findById(OWNER_ID).orElseThrow()));
            CompletableFuture<Void> mint = run(start, () ->
                sessionApiKeyService.mint(PARENT_KEY_VALUE, "agent-session-race", sessionId));
            // A refusal is the deactivation having committed first; the case
            // under test is the mint that won the locks and whose child the
            // sweep must then switch off.
            try {
                mint.get(30, TimeUnit.SECONDS);
            } catch (Exception expectedRefusal) {
            }
            deactivation.get(30, TimeUnit.SECONDS);

            // The deactivation committed, so the owner is deactivated: no
            // session key of the parent may be left active for it.
            assertNoActiveSessionKey(PARENT_KEY_ID, round);
        }
    }

    /**
     * The same race against a team leave: the mint is refused once the
     * membership is gone, or it commits first and the leave's sweep must
     * switch its child off with the team's other keys.
     */
    @Test
    void leaveRacingAMintLeavesNoActiveSessionKey() throws Exception {
        for (int round = 0; round < ROUNDS; round++) {
            resetRound(true);
            int sessionId = newSession();
            CyclicBarrier start = new CyclicBarrier(2);

            CompletableFuture<Void> leave = run(start, () -> membershipService.leave(OWNER_ID, TEAM_ID));
            CompletableFuture<Void> mint = run(start, () ->
                sessionApiKeyService.mint(PARENT_KEY_VALUE, "agent-session-race", sessionId));
            try {
                mint.get(30, TimeUnit.SECONDS);
            } catch (Exception expectedRefusal) {
            }
            leave.get(30, TimeUnit.SECONDS);

            // The leave committed, so the owner is no longer in the team: no
            // session key of the parent may be left active for it.
            assertNoActiveSessionKey(PARENT_KEY_ID, round);
        }
    }

    /** Restores the owner, the parent key and (after a leave) the membership. */
    private void resetRound(boolean membershipGone) {
        jdbc.update("UPDATE users SET is_active = true WHERE id = ?", OWNER_ID);
        jdbc.update("UPDATE api_keys SET is_active = true WHERE id = ?", PARENT_KEY_ID);
        jdbc.update("DELETE FROM api_keys WHERE parent_api_key_id = ?", PARENT_KEY_ID);
        if (membershipGone) {
            jdbc.update("""
                INSERT INTO team_members (user_id, team_id, is_owner, source)
                VALUES (?, ?, true, 'MANUAL')
                """, OWNER_ID, TEAM_ID);
        }
    }

    /**
     * Waits until some backend is blocked <em>by the transaction we are
     * holding the row in</em> — not merely until something, somewhere in this
     * database, waits on a lock. A test container is shared, and an unrelated
     * waiter would otherwise release the holder before the contended
     * statement ever reached the row, leaving the assertions to pass without
     * the race having happened. {@code pg_blocking_pids} names the blockers,
     * so we can insist it is ours.
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

    private int newSession() {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        Integer workspaceId = jdbc.queryForObject("""
            INSERT INTO agent_workspaces (name, base_branch, volume_name, created_by, ephemeral)
            VALUES (?, 'main', ?, 'test', FALSE)
            RETURNING id
            """, Integer.class, "mint-race-ws-" + suffix, "mint-race-vol-" + suffix);
        return jdbc.queryForObject("""
            INSERT INTO agent_sessions (
                workspace_id, task, status, created_by, open_pull_request, deploy_to_dev,
                screenshot_paths, no_push
            ) VALUES (?, 'mint-key', 'starting', 'test', FALSE, FALSE, '[]'::jsonb, TRUE)
            RETURNING id
            """, Integer.class, workspaceId);
    }

    private void assertNoSessionKey(int parentKeyId) {
        Integer count = jdbc.queryForObject(
            "SELECT COUNT(*) FROM api_keys WHERE parent_api_key_id = ?",
            Integer.class, parentKeyId);
        assertThat(count)
            .as("no session key may have been minted at all")
            .isZero();
    }

    private void assertNoActiveSessionKey(int parentKeyId, int round) {
        Integer count = jdbc.queryForObject(
            "SELECT COUNT(*) FROM api_keys WHERE parent_api_key_id = ? AND is_active",
            Integer.class, parentKeyId);
        assertThat(count)
            .as("round %d: no session key may stay active after the owner is deactivated or has left", round)
            .isZero();
    }

    private Boolean keyIsActive(int keyId) {
        return jdbc.queryForObject("SELECT is_active FROM api_keys WHERE id = ?", Boolean.class, keyId);
    }

    private Boolean ownerIsActive(int userId) {
        return jdbc.queryForObject("SELECT is_active FROM users WHERE id = ?", Boolean.class, userId);
    }

    private Boolean isMember(int userId, int teamId) {
        return jdbc.queryForObject(
            "SELECT EXISTS (SELECT 1 FROM team_members WHERE user_id = ? AND team_id = ?)",
            Boolean.class, userId, teamId);
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
