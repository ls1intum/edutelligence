package de.tum.cit.aet.logos.logoswebservice.common;

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
    void authFailureBudget_isSpentOnlyByConsume() {
        IpRateLimiterService limiter = new IpRateLimiterService(new RateLimitingProperties(true, 60, 2));

        // Merely checking never spends the budget.
        for (int i = 0; i < 10; i++) {
            assertTrue(limiter.hasAuthFailureBudget("9.9.9.9"));
        }

        limiter.consumeAuthFailure("9.9.9.9");
        assertTrue(limiter.hasAuthFailureBudget("9.9.9.9")); // one slot left
        limiter.consumeAuthFailure("9.9.9.9");
        assertFalse(limiter.hasAuthFailureBudget("9.9.9.9"));

        // A different source address still has its own budget.
        assertTrue(limiter.hasAuthFailureBudget("8.8.8.8"));
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
