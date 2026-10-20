package de.tum.cit.aet.logos.logoswebservice.common;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.UnaryOperator;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

class BackgroundRefreshedCacheTest {

    private static final long REFRESH_AFTER_MS = 5_000;
    private static final long MAX_STALE_MS = 60_000;
    private static final UnaryOperator<Object> PLUS_50 = v -> v instanceof Long l ? l + 50L : v;

    private final MutableClock clock = new MutableClock(Instant.parse("2026-03-15T12:00:00Z"));
    private final ExecutorService executor = Executors.newFixedThreadPool(2);

    @AfterEach
    void tearDown() {
        executor.shutdownNow();
    }

    private BackgroundRefreshedCache cache(java.util.concurrent.Executor refreshExecutor) {
        return new BackgroundRefreshedCache("test", REFRESH_AFTER_MS, MAX_STALE_MS, clock, refreshExecutor);
    }

    @Test
    void aFreshValueIsServedWithoutLoading() {
        BackgroundRefreshedCache cache = cache(executor);
        AtomicInteger loads = new AtomicInteger();

        assertThat(cache.<Long>get("k", () -> 100L + loads.getAndIncrement())).isEqualTo(100L);
        clock.advanceMillis(REFRESH_AFTER_MS - 1);
        assertThat(cache.<Long>get("k", () -> 100L + loads.getAndIncrement())).isEqualTo(100L);

        assertThat(loads).hasValue(1);
    }

    @Test
    void anExpiredValueAnswersAtOnceWhileOneLoadRunsInTheBackground() throws Exception {
        BackgroundRefreshedCache cache = cache(executor);
        cache.get("k", () -> 100L);
        clock.advanceMillis(REFRESH_AFTER_MS + 1);
        CountDownLatch release = new CountDownLatch(1);
        AtomicInteger loads = new AtomicInteger();

        for (int i = 0; i < 3; i++) {
            Object value = CompletableFuture.supplyAsync(() -> cache.get("k", () -> {
                loads.incrementAndGet();
                await(release);
                return 200L;
            })).get(2, TimeUnit.SECONDS);
            assertThat(value).isEqualTo(100L);
        }
        assertThat(loads).hasValue(1);

        release.countDown();
        assertThat(waitFor(() -> Long.valueOf(200L).equals(cache.view().get("k").value()))).isTrue();
    }

    @Test
    void aValuePastTheStaleLimitLoadsInLine() {
        BackgroundRefreshedCache cache = cache(task -> { });
        cache.get("k", () -> 100L);
        clock.advanceMillis(MAX_STALE_MS + 1);

        assertThat(cache.<Long>get("k", () -> 300L)).isEqualTo(300L);
    }

    @Test
    void aFailedBackgroundLoadKeepsTheExpiredValue() {
        BackgroundRefreshedCache cache = cache(Runnable::run);
        cache.get("k", () -> 100L);
        clock.advanceMillis(REFRESH_AFTER_MS + 1);

        Long value = cache.get("k", () -> {
            throw new IllegalStateException("database unavailable");
        });

        assertThat(value).isEqualTo(100L);
        assertThat(cache.view().get("k").value()).isEqualTo(100L);
    }

    @Test
    void aFailedInlineLoadReachesTheCaller() {
        BackgroundRefreshedCache cache = cache(executor);

        assertThatThrownBy(() -> cache.get("k", () -> {
            throw new IllegalStateException("database unavailable");
        })).isInstanceOf(IllegalStateException.class);
    }

    @Test
    void anUpdateDuringALoadIsReplayedOntoTheLoadedValue() throws Exception {
        BackgroundRefreshedCache cache = cache(executor);
        cache.get("k", () -> 100L);
        clock.advanceMillis(MAX_STALE_MS + 1);
        CountDownLatch loading = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);

        CompletableFuture<Object> load = CompletableFuture.supplyAsync(() -> cache.get("k", () -> {
            loading.countDown();
            await(release);
            return 100L;
        }), executor);
        assertThat(loading.await(5, TimeUnit.SECONDS)).isTrue();

        cache.update("k", PLUS_50);
        assertThat(cache.view().get("k").value()).isEqualTo(150L);

        release.countDown();
        assertThat(load.get(5, TimeUnit.SECONDS)).isEqualTo(150L);
        assertThat(cache.view().get("k").value()).isEqualTo(150L);
    }

    @Test
    void anUpdateWithoutACachedValueChangesNothing() {
        BackgroundRefreshedCache cache = cache(executor);

        cache.update("k", PLUS_50);

        assertThat(cache.view()).doesNotContainKey("k");
    }

    /**
     * A late load can register its flight after another caller already
     * installed a fresh value. An update then queues its change; the early
     * return must drop it, or the next load counts it twice.
     */
    @Test
    void aLoadThatFindsAFreshValueDropsTheChangesQueuedAgainstIt() {
        BackgroundRefreshedCache cache = cache(executor);
        cache.get("k", () -> 100L);

        cache.markInflight("k");
        cache.update("k", PLUS_50);
        assertThat(cache.view().get("k").value()).isEqualTo(150L);
        cache.clearInflight("k");

        cache.refresh("k", () -> {
            throw new AssertionError("the early return must not load");
        }, clock.millis());

        clock.advanceMillis(MAX_STALE_MS + 1);
        assertThat(cache.<Long>get("k", () -> 150L)).isEqualTo(150L);
    }

    @Test
    void aZeroRefreshIntervalLoadsOnEveryRead() {
        BackgroundRefreshedCache cache = new BackgroundRefreshedCache("test", 0, 0, clock, executor);
        AtomicInteger loads = new AtomicInteger();

        cache.get("k", loads::incrementAndGet);
        cache.get("k", loads::incrementAndGet);

        assertThat(loads).hasValue(2);
        assertThat(cache.view()).isEmpty();
    }

    private static void await(CountDownLatch latch) {
        try {
            if (!latch.await(5, TimeUnit.SECONDS)) {
                throw new IllegalStateException("timed out");
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(e);
        }
    }

    private static boolean waitFor(java.util.function.BooleanSupplier condition) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (!condition.getAsBoolean() && System.nanoTime() < deadline) {
            Thread.sleep(10);
        }
        return condition.getAsBoolean();
    }

    private static final class MutableClock extends Clock {
        private volatile Instant instant;

        MutableClock(Instant instant) {
            this.instant = instant;
        }

        void advanceMillis(long millis) {
            instant = instant.plusMillis(millis);
        }

        @Override
        public ZoneOffset getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return Clock.fixed(instant, zone);
        }

        @Override
        public Instant instant() {
            return instant;
        }
    }
}
