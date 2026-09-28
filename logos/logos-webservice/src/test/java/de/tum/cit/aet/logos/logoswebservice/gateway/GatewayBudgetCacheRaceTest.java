package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.YearMonth;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.ResultSetExtractor;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/**
 * Regression for the budget-cache race: a {@link GatewayBudgetService#noteReservation}
 * that lands while {@code cached()} is reloading must not be discarded when the
 * reload installs.
 */
class GatewayBudgetCacheRaceTest {

    private static final int KEY_ID = 42;
    private static final long TTL_SECONDS = 5;
    private static final Instant T0 = Instant.parse("2026-03-15T12:00:00Z");

    private NamedParameterJdbcTemplate jdbc;
    private MutableClock clock;
    private GatewayBudgetService budget;
    private ExecutorService executor;

    private final AtomicLong usageFromDb = new AtomicLong(100L);
    private volatile CountDownLatch blockUsageLoad;
    private volatile CountDownLatch usageLoadStarted;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() throws Exception {
        jdbc = mock(NamedParameterJdbcTemplate.class);
        clock = new MutableClock(T0);
        budget = new GatewayBudgetService(jdbc, TTL_SECONDS, clock);
        executor = Executors.newFixedThreadPool(2);

        when(jdbc.query(anyString(), any(MapSqlParameterSource.class), any(ResultSetExtractor.class)))
            .thenAnswer(invocation -> {
                ResultSetExtractor<Object> extractor = invocation.getArgument(2);
                // Limit lookup: return a high budget so enforce never 402s on limit alone.
                return 1_000_000_000L;
            });

        when(jdbc.queryForObject(anyString(), any(MapSqlParameterSource.class), eq(Long.class)))
            .thenAnswer(invocation -> {
                CountDownLatch started = usageLoadStarted;
                if (started != null) {
                    started.countDown();
                }
                CountDownLatch block = blockUsageLoad;
                if (block != null && !block.await(5, TimeUnit.SECONDS)) {
                    throw new IllegalStateException("Timed out blocked in usage load");
                }
                return usageFromDb.get();
            });
    }

    @AfterEach
    void tearDown() {
        executor.shutdownNow();
    }

    @Test
    void noteReservationDuringRefresh_isMergedIntoInstalledSnapshot() throws Exception {
        GatewayKey key = applicationKey(KEY_ID);

        // Prime a fresh usage snapshot.
        budget.enforceCloudBudget(key);
        String usageKey = usageCacheKey(KEY_ID);
        assertThat(budget.cacheView().get(usageKey).value()).isEqualTo(100L);

        // Expire the snapshot and block the reload so noteReservation can race it.
        clock.advanceMillis(TTL_SECONDS * 1000L + 1);
        blockUsageLoad = new CountDownLatch(1);
        usageLoadStarted = new CountDownLatch(1);
        usageFromDb.set(100L); // DB has not yet observed the new reservation

        Future<?> refresh = executor.submit(() -> budget.enforceCloudBudget(key));
        assertThat(usageLoadStarted.await(5, TimeUnit.SECONDS)).isTrue();

        budget.noteReservation(key, 50L);

        // Live entry still shows the bump for concurrent readers.
        assertThat(budget.cacheView().get(usageKey).value()).isEqualTo(150L);

        blockUsageLoad.countDown();
        refresh.get(5, TimeUnit.SECONDS);

        // Reload must keep the reservation — not reinstall the stale 100.
        assertThat(budget.cacheView().get(usageKey).value()).isEqualTo(150L);
    }

    private static String usageCacheKey(int apiKeyId) {
        String monthStart = YearMonth.from(T0.atZone(ZoneOffset.UTC)).atDay(1).toString();
        return "usage:key:" + apiKeyId + ":" + monthStart;
    }

    private static GatewayKey applicationKey(int id) {
        return new GatewayKey(id, "lg-x", "k", ApiKeyType.application,
            null, null, "test", false, null, 0, "BILLING");
    }

    /** Clock that tests can advance without sleeping. */
    private static final class MutableClock extends Clock {
        private final ZoneOffset zone = ZoneOffset.UTC;
        private volatile Instant instant;

        MutableClock(Instant instant) {
            this.instant = instant;
        }

        void advanceMillis(long millis) {
            instant = instant.plusMillis(millis);
        }

        @Override
        public ZoneOffset getZone() {
            return zone;
        }

        @Override
        public Clock withZone(java.time.ZoneId zone) {
            return Clock.fixed(instant, zone);
        }

        @Override
        public Instant instant() {
            return instant;
        }
    }
}
