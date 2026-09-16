package de.tum.cit.aet.logos.logoswebservice.common;

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
