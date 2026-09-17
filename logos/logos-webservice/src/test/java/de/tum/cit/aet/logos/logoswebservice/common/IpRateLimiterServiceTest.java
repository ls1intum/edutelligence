package de.tum.cit.aet.logos.logoswebservice.common;

import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class IpRateLimiterServiceTest {

    @Test
    void enforcePublicEndpoint_rejectsOnceTheWindowIsFull() {
        IpRateLimiterService limiter = new IpRateLimiterService(new RateLimitingProperties(true, 2, 20));

        limiter.enforcePublicEndpoint("1.2.3.4", "info");
        limiter.enforcePublicEndpoint("1.2.3.4", "info");

        RateLimitExceededException ex = assertThrows(RateLimitExceededException.class,
                () -> limiter.enforcePublicEndpoint("1.2.3.4", "info"));
        assertEquals(60, ex.getRetryAfterSeconds());
    }

    @Test
    void enforcePublicEndpoint_tracksEachClientSeparately() {
        IpRateLimiterService limiter = new IpRateLimiterService(new RateLimitingProperties(true, 1, 20));

        limiter.enforcePublicEndpoint("1.2.3.4", "info");
        // A different client still has its own budget.
        limiter.enforcePublicEndpoint("5.6.7.8", "info");
    }

    @Test
    void enforcePublicEndpoint_tracksEachBucketSeparately() {
        IpRateLimiterService limiter = new IpRateLimiterService(new RateLimitingProperties(true, 1, 20));

        limiter.enforcePublicEndpoint("1.2.3.4", "info");
        // A different bucket for the same client is a separate budget.
        limiter.enforcePublicEndpoint("1.2.3.4", "health");
    }

    @Test
    void enforcePublicEndpoint_disabledGlobally_neverRejects() {
        IpRateLimiterService limiter = new IpRateLimiterService(new RateLimitingProperties(false, 1, 20));

        for (int i = 0; i < 5; i++) {
            limiter.enforcePublicEndpoint("1.2.3.4", "info");
        }
    }

    @Test
    void authFailureSlot_reservedOnlyOnceLimitIsReached() {
        IpRateLimiterService limiter = new IpRateLimiterService(new RateLimitingProperties(true, 60, 2));

        assertTrue(limiter.tryReserveAuthFailureSlot("9.9.9.9"));
        assertTrue(limiter.tryReserveAuthFailureSlot("9.9.9.9"));
        assertFalse(limiter.tryReserveAuthFailureSlot("9.9.9.9"));

        // A different source address still has its own budget.
        assertTrue(limiter.tryReserveAuthFailureSlot("8.8.8.8"));
    }

    @Test
    void releaseAuthFailureSlot_givesTheBudgetBackOnSuccess() {
        IpRateLimiterService limiter = new IpRateLimiterService(new RateLimitingProperties(true, 60, 1));

        assertTrue(limiter.tryReserveAuthFailureSlot("9.9.9.9"));
        assertFalse(limiter.tryReserveAuthFailureSlot("9.9.9.9"));

        // The caller that reserved the slot authenticated successfully after all.
        limiter.releaseAuthFailureSlot("9.9.9.9");
        assertTrue(limiter.tryReserveAuthFailureSlot("9.9.9.9"));
    }

    @Test
    void concurrentAuthFailures_neverExceedTheConfiguredLimit() throws InterruptedException {
        // Regression: hasAuthFailureBudget + consumeAuthFailure used to be a check-then-record pair with the
        // database lookup in between, so a burst of concurrent requests could all observe the same free slot
        // before any of them recorded a failure. tryReserveAuthFailureSlot checks and reserves atomically, so
        // concurrency must not let more callers through than the configured limit.
        int limit = 5;
        int concurrentCallers = 50;
        IpRateLimiterService limiter = new IpRateLimiterService(new RateLimitingProperties(true, 60, limit));

        ExecutorService pool = Executors.newFixedThreadPool(concurrentCallers);
        CountDownLatch ready = new CountDownLatch(concurrentCallers);
        CountDownLatch start = new CountDownLatch(1);
        AtomicInteger reserved = new AtomicInteger();
        try {
            for (int i = 0; i < concurrentCallers; i++) {
                pool.submit(() -> {
                    ready.countDown();
                    try {
                        start.await();
                    }
                    catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        return;
                    }
                    if (limiter.tryReserveAuthFailureSlot("9.9.9.9")) {
                        reserved.incrementAndGet();
                    }
                });
            }
            ready.await();
            start.countDown();
            pool.shutdown();
            assertTrue(pool.awaitTermination(10, TimeUnit.SECONDS));
        }
        finally {
            pool.shutdownNow();
        }

        assertEquals(limit, reserved.get());
    }

    @Test
    void concurrentValidRequests_eachReleaseTheirOwnReservation() throws InterruptedException {
        // Regression: releasing the reservation only after downstream work (e.g. the orchestrator call) meant a
        // burst of concurrent *valid* requests could occupy every slot while their downstream work was in
        // flight, causing the next valid request to see 429 even though every caller held a genuine key. The
        // fix is structural (ModelController releases immediately after key validation, before calling out) —
        // this test pins the limiter-level contract that a reserve immediately followed by a release, repeated
        // concurrently, never exhausts the budget no matter how many callers do it.
        int limit = 5;
        int concurrentCallers = 50;
        IpRateLimiterService limiter = new IpRateLimiterService(new RateLimitingProperties(true, 60, limit));

        ExecutorService pool = Executors.newFixedThreadPool(concurrentCallers);
        CountDownLatch ready = new CountDownLatch(concurrentCallers);
        CountDownLatch start = new CountDownLatch(1);
        AtomicInteger admitted = new AtomicInteger();
        try {
            for (int i = 0; i < concurrentCallers; i++) {
                pool.submit(() -> {
                    ready.countDown();
                    try {
                        start.await();
                    }
                    catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        return;
                    }
                    if (limiter.tryReserveAuthFailureSlot("9.9.9.9")) {
                        admitted.incrementAndGet();
                        // Simulates a "key turned out valid" caller: release right away, as
                        // ModelController now does, rather than holding the slot through downstream work.
                        limiter.releaseAuthFailureSlot("9.9.9.9");
                    }
                });
            }
            ready.await();
            start.countDown();
            pool.shutdown();
            assertTrue(pool.awaitTermination(10, TimeUnit.SECONDS));
        }
        finally {
            pool.shutdownNow();
        }

        // Every caller released its own reservation immediately, so none of the concurrency should have been
        // throttled — a stronger guarantee than merely "at least `limit` got through".
        assertEquals(concurrentCallers, admitted.get());
    }

    @Test
    void evictStaleWindows_reclaimsWindowsOnceTheyHaveNothingLeftAfterPruning() throws InterruptedException {
        // Regression: neither store ever removed a key, so /info (unauthenticated, therefore queried by an
        // ever-changing set of source addresses) would grow the map for the life of the process. A short window
        // (instead of the real 1-minute one) lets this test observe real-time expiry without sleeping a minute.
        IpRateLimiterService limiter = new IpRateLimiterService(new RateLimitingProperties(true, 1000, 1000), Duration.ofMillis(20));
        int distinctAddresses = 500;
        for (int i = 0; i < distinctAddresses; i++) {
            limiter.enforcePublicEndpoint("10.0.0." + i, "info");
        }
        assertEquals(distinctAddresses, limiter.trackedWindowCount());

        Thread.sleep(60); // longer than the 20ms window, so every window has nothing left to prune
        limiter.evictStaleWindows();
        assertEquals(0, limiter.trackedWindowCount());
    }

    @Test
    void evictStaleWindows_keepsWindowsWithRecentActivity() {
        IpRateLimiterService limiter = new IpRateLimiterService(new RateLimitingProperties(true, 1000, 1000));

        limiter.enforcePublicEndpoint("10.0.0.1", "info");
        limiter.evictStaleWindows();

        // The call above is well within the (real, 1-minute) window, so the sweep must not have touched it.
        assertEquals(1, limiter.trackedWindowCount());
    }

    @Test
    void clientIp_prefersFirstHopOfForwardedFor() {
        var request = new org.springframework.mock.web.MockHttpServletRequest();
        request.addHeader("X-Forwarded-For", "203.0.113.5, 10.0.0.1");
        request.setRemoteAddr("10.0.0.1");

        assertEquals("203.0.113.5", IpRateLimiterService.clientIp(request));
    }

    @Test
    void clientIp_fallsBackToRemoteAddr() {
        var request = new org.springframework.mock.web.MockHttpServletRequest();
        request.setRemoteAddr("192.0.2.9");

        assertEquals("192.0.2.9", IpRateLimiterService.clientIp(request));
    }
}
