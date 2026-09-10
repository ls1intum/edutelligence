package de.tum.cit.aet.logos.logoswebservice.configuration;

import static org.assertj.core.api.Assertions.assertThat;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Delayed;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.scheduling.Trigger;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TokenPriceRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelMetricsService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorNotificationService;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.BudgetBucketProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryBillingRepository;

/**
 * Regression for the provider type change's price close stamping. The close
 * runs in the change's transaction only after that transaction took the
 * provider's advisory lock, but PostgreSQL fixes a transaction's NOW() at its
 * first statement - before the lock wait. A catalogue price write holding the
 * lock can therefore commit a new-generation row (valid_from stamped from the
 * wall clock) while the change waits, and a close stamped with the change's
 * fixed NOW() would assign that row a valid_to before its valid_from: an
 * impossible interval that the historical billing lookup
 * ({@code valid_from <= t AND (valid_to IS NULL OR valid_to > t)}) can never
 * match, losing the billing of every request made while that price was
 * active. The close must also stamp every row it closes with one single
 * post-lock timestamp: a volatile per-row stamp could give the provider's
 * prompt, completion, and reasoning rows different valid_to boundaries, and
 * a request timestamp between two of them would bill only part of its
 * usage. These tests run against the real Postgres container, so the
 * advisory-lock interleaving is exercised end to end.
 */
@SpringBootTest
@Import({TestContainersConfig.class, TokenPriceCloseLockInterleavingTest.SchedulingDisabled.class})
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    "logos.auth.roles.logos-admin=itg-admin",
    "logos.auth.roles.app-admin=chair-member",
    "logos.auth.sync-debounce-minutes=5"
})
@Sql(scripts = {"/sql/cleanup-metrics.sql", "/sql/seed-metrics.sql",
               "/sql/cleanup-price-interleaving.sql", "/sql/seed-price-interleaving.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-price-interleaving.sql", "/sql/cleanup-metrics.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class TokenPriceCloseLockInterleavingTest {

    @Autowired
    ProviderRepository providerRepository;
    @Autowired
    TokenPriceRepository tokenPriceRepository;
    @Autowired
    LogEntryBillingRepository logEntryBillingRepository;
    @Autowired
    JdbcTemplate jdbc;
    @Autowired
    PlatformTransactionManager transactionManager;

    @MockitoBean
    JwtDecoder jwtDecoder;
    // The change notifies the orchestrator after commit; keep that off the
    // real websocket in this context.
    @MockitoBean
    OrchestratorNotificationService orchestratorNotificationService;
    // The catalogue refresh would reach the live litellm catalog; the test
    // drives the interleaving with a raw write instead, so mock it like the
    // other metrics tests do.
    @MockitoBean
    PriceUpdaterService priceUpdaterService;

    /**
     * The startup @Scheduled runs (metrics derivation, price and capability
     * refreshes) would move the prices out from under the interleaving
     * below. A no-op TaskScheduler makes this context deterministic - the
     * test drives both sides of the race directly.
     */
    @TestConfiguration
    static class SchedulingDisabled {
        @Bean
        TaskScheduler taskScheduler() {
            ScheduledFuture<?> done = new FinishedFuture();
            return new TaskScheduler() {
                @Override
                public ScheduledFuture<?> schedule(Runnable task, Trigger trigger) { return done; }
                @Override
                public ScheduledFuture<?> schedule(Runnable task, Instant startTime) { return done; }
                @Override
                public ScheduledFuture<?> scheduleAtFixedRate(Runnable task, Instant startTime, Duration fixedRate) { return done; }
                @Override
                public ScheduledFuture<?> scheduleAtFixedRate(Runnable task, Duration fixedRate) { return done; }
                @Override
                public ScheduledFuture<?> scheduleWithFixedDelay(Runnable task, Instant startTime, Duration fixedDelay) { return done; }
                @Override
                public ScheduledFuture<?> scheduleWithFixedDelay(Runnable task, Duration fixedDelay) { return done; }
            };
        }

        /** A finished future returned by the no-op scheduler. */
        record FinishedFuture() implements ScheduledFuture<Object> {
            @Override
            public long getDelay(TimeUnit unit) { return 0; }
            @Override
            public int compareTo(Delayed other) { return 0; }
            @Override
            public boolean cancel(boolean mayInterruptIfRunning) { return true; }
            @Override
            public boolean isCancelled() { return true; }
            @Override
            public boolean isDone() { return true; }
            @Override
            public Object get() { return null; }
            @Override
            public Object get(long timeout, TimeUnit unit) { return null; }
        }
    }

    @Test
    void priceCloseWaitingForCatalogueWriteKeepsCommittedRowBillable() throws Exception {
        // The provider type change side, mirroring the statement order of
        // ProviderService.updateProvider: the findById starts the
        // transaction (and with it fixes its NOW()), the advisory lock
        // serializes the change with the in-flight catalogue writes, and the
        // price close runs only after the lock is taken.
        TransactionTemplate providerTx = new TransactionTemplate(transactionManager);
        CountDownLatch providerStarted = new CountDownLatch(1);
        CountDownLatch releaseProvider = new CountDownLatch(1);

        try (ExecutorService providerPool = Executors.newSingleThreadExecutor();
             ExecutorService cataloguePool = Executors.newSingleThreadExecutor()) {
            Future<Integer> provider = providerPool.submit(() -> providerTx.execute(status -> {
                providerRepository.findById(6101).orElseThrow();
                providerStarted.countDown();
                try {
                    if (!releaseProvider.await(30, TimeUnit.SECONDS)) {
                        status.setRollbackOnly();
                        return 0;
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    status.setRollbackOnly();
                    return 0;
                }
                providerRepository.lockProviderDerivation(ModelMetricsService.providerDerivationLockKey(6101));
                tokenPriceRepository.closeCurrentPricesByProviderId(6101);
                return 1;
            }));

            assertThat(providerStarted.await(10, TimeUnit.SECONDS))
                .as("the provider transaction started and fixed its NOW()")
                .isTrue();

            // The in-flight catalogue price write side, mirroring
            // PriceUpdaterService.storeFetchedCataloguePrices: the
            // wall-clock valid_from is captured before the write
            // transaction, which takes the same provider lock before opening
            // the new price generation. It starts only after the provider
            // transaction above, so its valid_from is later than that
            // transaction's fixed NOW().
            Instant validFrom = Instant.now();
            CountDownLatch catalogueWritten = new CountDownLatch(1);
            CountDownLatch releaseCatalogue = new CountDownLatch(1);
            Future<Integer> catalogue = cataloguePool.submit(() -> {
                TransactionTemplate catalogueTx = new TransactionTemplate(transactionManager);
                return catalogueTx.execute(status -> {
                    providerRepository.lockProviderDerivation(ModelMetricsService.providerDerivationLockKey(6101));
                    jdbc.update(
                        "INSERT INTO token_prices (id, type_id, model_id, provider_id, valid_from, price_per_k_unit) "
                            + "VALUES (92105, (SELECT id FROM token_types WHERE name = 'billed_input_uncached'), 5101, 6101, ?, 2500)",
                        Timestamp.from(validFrom));
                    catalogueWritten.countDown();
                    try {
                        if (!releaseCatalogue.await(30, TimeUnit.SECONDS)) {
                            status.setRollbackOnly();
                        }
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        status.setRollbackOnly();
                    }
                    return 1;
                });
            });

            assertThat(catalogueWritten.await(10, TimeUnit.SECONDS))
                .as("the catalogue write holds the provider lock with its new row")
                .isTrue();

            // Send the provider transaction onto the lock the catalogue
            // write holds: it must park there instead of closing the prices
            // now, or the interleaving below proves nothing.
            releaseProvider.countDown();
            assertThat(awaitLockWaiter())
                .as("the provider transaction waited for the catalogue write's lock")
                .isTrue();

            // The catalogue write commits: its row becomes visible with a
            // valid_from after the provider transaction's fixed NOW(), and
            // the lock is released with the commit. Only then does the
            // provider transaction's price close run.
            releaseCatalogue.countDown();
            assertThat(catalogue.get(30, TimeUnit.SECONDS)).isEqualTo(1);
            assertThat(provider.get(30, TimeUnit.SECONDS)).isEqualTo(1);
        }

        // The close saw the row committed under the lock and closed it, but
        // a stamp taken from the provider transaction's fixed NOW() would
        // predate the row's valid_from, inverting the interval.
        assertThat(jdbc.queryForObject(
            "SELECT COUNT(*) FROM token_prices WHERE provider_id = 6101 "
                + "AND valid_to IS NOT NULL AND valid_to < valid_from", Long.class))
            .as("the close assigned no row a valid_to before its valid_from")
            .isZero();
        assertThat(jdbc.queryForObject(
            "SELECT COUNT(*) FROM token_prices WHERE id = 92105 "
                + "AND valid_to IS NOT NULL AND valid_to > valid_from", Long.class))
            .as("the committed catalogue row was closed after its valid_from")
            .isOne();

        // One close stamps every row it closes with one boundary: a
        // per-row-volatile stamp could split the prompt, completion, and
        // reasoning rows' valid_to values, and a request timestamp between
        // two of them would bill only part of its usage.
        assertThat(jdbc.queryForObject(
            "SELECT COUNT(DISTINCT valid_to) FROM token_prices "
                + "WHERE provider_id = 6101 AND valid_to IS NOT NULL", Long.class))
            .as("every row closed by the same provider change shares one valid_to")
            .isOne();

        // Historical billing: a request made while the closed row was the
        // active price must still bill at that row's price - the lookup
        // admits a row only for request times inside [valid_from, valid_to).
        // The two requests' billing windows are disjoint by construction:
        // [requestTs, boundaryTs) for the mid-interval request, [boundaryTs,
        // ...) for the boundary request.
        Timestamp boundaryTs = jdbc.queryForObject(
            "SELECT valid_to - INTERVAL '1 microsecond' FROM token_prices WHERE id = 92105",
            Timestamp.class);
        Timestamp requestTs = jdbc.queryForObject(
            "SELECT valid_from + (valid_to - valid_from) / 2 FROM token_prices WHERE id = 92105",
            Timestamp.class);
        jdbc.update(
            "INSERT INTO log_entry (id, timestamp_request, provider_id, model_id, api_key_id, team_id, result_status) "
                + "VALUES (90101, ?, 6101, 5101, 5301, 2003, 'success')",
            requestTs);
        jdbc.update("INSERT INTO usage_tokens (type_id, log_entry_id, token_count) VALUES (9101, 90101, 1000)");

        long cost = logEntryBillingRepository
            .findKeyBudgetHistory(2003,
                Timestamp.from(requestTs.toInstant().minusSeconds(60)),
                boundaryTs,
                "hour")
            .stream().mapToLong(BudgetBucketProjection::getCostMicroCents).sum();
        assertThat(cost)
            .as("the request inside the closed row's interval bills at that row's price "
                + "(1000 tokens x 2500 microcents per 1K)")
            .isEqualTo(1000L * 2500 / 1000);

        // Full billing at the shared boundary: a request one microsecond
        // before it, with usage of the provider's prompt, completion, and
        // reasoning tokens, must bill every type against its closed row -
        // the request sits inside every type's [valid_from, valid_to) only
        // because they all end at the same boundary.
        jdbc.update(
            "INSERT INTO log_entry (id, timestamp_request, provider_id, model_id, api_key_id, team_id, result_status) "
                + "VALUES (90102, ?, 6101, 5101, 5301, 2003, 'success')",
            boundaryTs);
        jdbc.update("INSERT INTO usage_tokens (type_id, log_entry_id, token_count) VALUES (9101, 90102, 1000)");
        jdbc.update("INSERT INTO usage_tokens (type_id, log_entry_id, token_count) VALUES (9102, 90102, 500)");
        jdbc.update("INSERT INTO usage_tokens (type_id, log_entry_id, token_count) VALUES (9103, 90102, 200)");

        long fullCost = logEntryBillingRepository
            .findKeyBudgetHistory(2003,
                boundaryTs,
                Timestamp.from(boundaryTs.toInstant().plusSeconds(60)),
                "hour")
            .stream().mapToLong(BudgetBucketProjection::getCostMicroCents).sum();
        // The token-cost decomposition splits the 500 completion tokens into
        // the 300 text remainder (billed_output_text at 2000/1K) and the 200
        // reasoning tokens (billed_output_reasoning at 3000/1K) - the reasoning
        // tokens are not billed a second time inside the completion count.
        assertThat(fullCost)
            .as("the request at the shared boundary bills every token type "
                + "(1000 x 2500 + (500 - 200) x 2000 + 200 x 3000 over 1K)")
            .isEqualTo(1000L * 2500 / 1000 + 300L * 2000 / 1000 + 200L * 3000 / 1000);
    }

    /**
     * Waits up to 15 s for a session blocked on an advisory-lock call: a
     * parked transaction's current query is the lock statement itself.
     */
    private boolean awaitLockWaiter() throws InterruptedException {
        long deadline = System.currentTimeMillis() + 15_000;
        while (System.currentTimeMillis() < deadline) {
            if (lockWaiterVisible()) {
                return true;
            }
            Thread.sleep(50);
        }
        return false;
    }

    private boolean lockWaiterVisible() {
        Long waiting = jdbc.queryForObject(
            "SELECT COUNT(*) FROM pg_stat_activity "
                + "WHERE wait_event_type = 'Lock' "
                + "AND query ILIKE '%pg_advisory_xact_lock%' "
                + "AND pid <> pg_backend_pid()",
            Long.class);
        return waiting != null && waiting > 0;
    }
}
