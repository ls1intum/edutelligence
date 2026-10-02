package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.YearMonth;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/**
 * Regression for budget-cache races around {@link GatewayBudgetService#noteReservation}
 * and concurrent snapshot refreshes.
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

        when(jdbc.query(anyString(), any(MapSqlParameterSource.class), any(org.springframework.jdbc.core.ResultSetExtractor.class)))
            .thenAnswer(invocation -> 1_000_000_000L);

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
    void noteReservationDuringRefresh_isMergedWhenLoadMissedTheRow() throws Exception {
        GatewayKey key = applicationKey(KEY_ID);

        budget.enforceCloudBudget(key);
        String usageKey = usageCacheKey(KEY_ID);
        assertThat(budget.cacheView().get(usageKey).value()).isEqualTo(100L);

        clock.advanceMillis(TTL_SECONDS * 1000L + 1);
        blockUsageLoad = new CountDownLatch(1);
        usageLoadStarted = new CountDownLatch(1);
        usageFromDb.set(100L);

        Future<?> refresh = executor.submit(() -> budget.enforceCloudBudget(key));
        assertThat(usageLoadStarted.await(5, TimeUnit.SECONDS)).isTrue();

        budget.noteReservation(key, 50L);
        assertThat(budget.cacheView().get(usageKey).value()).isEqualTo(150L);

        blockUsageLoad.countDown();
        refresh.get(5, TimeUnit.SECONDS);

        assertThat(budget.cacheView().get(usageKey).value()).isEqualTo(150L);
    }

    @Test
    void nextRefreshReplacesInflatedValueWithDatabaseTotal() {
        GatewayKey key = applicationKey(KEY_ID);
        budget.enforceCloudBudget(key);
        String usageKey = usageCacheKey(KEY_ID);

        budget.noteReservation(key, 50L);
        assertThat(budget.cacheView().get(usageKey).value()).isEqualTo(150L);

        clock.advanceMillis(TTL_SECONDS * 1000L + 1);
        usageFromDb.set(120L);
        budget.enforceCloudBudget(key);

        assertThat(budget.cacheView().get(usageKey).value()).isEqualTo(120L);
    }

    /**
     * A late refresh can register {@code inflight} after another caller already
     * installed a fresh entry. {@code noteReservation} then queues pending; the
     * early-return path must drop it or the next refresh double-counts.
     */
    @Test
    void freshEntryEarlyReturn_doesNotDoubleCountReservationOnNextRefresh() throws Exception {
        GatewayKey key = applicationKey(KEY_ID);
        budget.enforceCloudBudget(key);
        String usageKey = usageCacheKey(KEY_ID);

        var inflightField = GatewayBudgetService.class.getDeclaredField("inflight");
        inflightField.setAccessible(true);
        @SuppressWarnings("unchecked")
        var inflight = (ConcurrentHashMap<String, CompletableFuture<?>>) inflightField.get(budget);
        inflight.put(usageKey, new CompletableFuture<>());

        budget.noteReservation(key, 50L);
        assertThat(budget.cacheView().get(usageKey).value()).isEqualTo(150L);

        // Drop the planted flight so refresh can become the winner; pending stays.
        inflight.remove(usageKey);

        Class<?> loaderClass = null;
        for (Class<?> nested : GatewayBudgetService.class.getDeclaredClasses()) {
            if (nested.getSimpleName().equals("Loader")) {
                loaderClass = nested;
                break;
            }
        }
        assertThat(loaderClass).isNotNull();
        Object loader = Proxy.newProxyInstance(
            loaderClass.getClassLoader(),
            new Class<?>[] { loaderClass },
            (proxy, method, args) -> {
                if ("load".equals(method.getName())) {
                    throw new AssertionError("early-return path must not load from the database");
                }
                throw new UnsupportedOperationException(method.getName());
            });

        Method refresh = GatewayBudgetService.class.getDeclaredMethod(
            "refresh", String.class, loaderClass, long.class);
        refresh.setAccessible(true);
        refresh.invoke(budget, usageKey, loader, clock.millis());

        clock.advanceMillis(TTL_SECONDS * 1000L + 1);
        usageFromDb.set(150L);
        budget.enforceCloudBudget(key);

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
