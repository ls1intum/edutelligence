package de.tum.cit.aet.logos.logoswebservice.common;

import java.time.Duration;
import java.util.ArrayDeque;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Service;

import jakarta.servlet.http.HttpServletRequest;

/**
 * In-memory, per-IP sliding-window rate limiter for endpoints that take no valid credential.
 *
 * <p>
 * Two categories are covered:
 * <ul>
 * <li>Public endpoints (e.g. {@code /info}) — every request is bounded, via {@link #enforcePublicEndpoint}.</li>
 * <li>The failure path of API-key authentication (e.g. {@code /logosdb/get_model_health}) — only a 401 spends
 * budget, via {@link #hasAuthFailureBudget} (check before authenticating) and {@link #consumeAuthFailure} (spend
 * after a failure), so traffic that keeps authenticating successfully never approaches the limit.</li>
 * </ul>
 *
 * <p>
 * State is process-local. logos-webservice runs as a single instance, so this needs no distributed backing store;
 * if that ever changes, this is the place to swap in a shared store (e.g. Redis) behind the same interface.
 */
@Service
public class IpRateLimiterService {

    private static final Duration WINDOW = Duration.ofMinutes(1);

    private final RateLimitingProperties properties;

    private final ConcurrentHashMap<String, ArrayDeque<Long>> requestWindows = new ConcurrentHashMap<>();

    public IpRateLimiterService(RateLimitingProperties properties) {
        this.properties = properties;
    }

    /**
     * Raises {@link RateLimitExceededException} once {@code clientIp} exceeds the configured public-endpoint RPM
     * for {@code bucket}. Used for endpoints that admit every caller unconditionally (no credential), so the
     * request itself has to be bounded.
     *
     * @param clientIp the caller's address (see {@link #clientIp(HttpServletRequest)})
     * @param bucket   a name distinguishing this endpoint's budget from others sharing the limiter
     */
    public void enforcePublicEndpoint(String clientIp, String bucket) {
        if (!properties.enabled() || properties.publicEndpointRequestsPerMinute() <= 0 || clientIp == null) {
            return;
        }
        if (!tryConsume(key(clientIp, bucket), properties.publicEndpointRequestsPerMinute())) {
            throw new RateLimitExceededException(WINDOW.toSeconds());
        }
    }

    /**
     * Whether {@code clientIp} still has an unspent authentication-failure slot, without spending one. Call before
     * attempting authentication; pair with {@link #consumeAuthFailure} on the failure path only.
     */
    public boolean hasAuthFailureBudget(String clientIp) {
        if (!properties.enabled() || properties.authFailureRequestsPerMinute() <= 0 || clientIp == null) {
            return true;
        }
        return count(key(clientIp, "auth_fail")) < properties.authFailureRequestsPerMinute();
    }

    /** Spends one unit of {@code clientIp}'s authentication-failure budget, unconditionally. */
    public void consumeAuthFailure(String clientIp) {
        if (!properties.enabled() || properties.authFailureRequestsPerMinute() <= 0 || clientIp == null) {
            return;
        }
        record(key(clientIp, "auth_fail"));
    }

    private boolean tryConsume(String key, int limit) {
        ArrayDeque<Long> window = requestWindows.computeIfAbsent(key, k -> new ArrayDeque<>());
        synchronized (window) {
            prune(window);
            if (window.size() >= limit) {
                return false;
            }
            window.addLast(System.nanoTime());
            return true;
        }
    }

    private int count(String key) {
        ArrayDeque<Long> window = requestWindows.computeIfAbsent(key, k -> new ArrayDeque<>());
        synchronized (window) {
            prune(window);
            return window.size();
        }
    }

    private void record(String key) {
        ArrayDeque<Long> window = requestWindows.computeIfAbsent(key, k -> new ArrayDeque<>());
        synchronized (window) {
            window.addLast(System.nanoTime());
        }
    }

    private void prune(ArrayDeque<Long> window) {
        long cutoff = System.nanoTime() - WINDOW.toNanos();
        while (!window.isEmpty() && window.peekFirst() < cutoff) {
            window.pollFirst();
        }
    }

    private static String key(String clientIp, String bucket) {
        return bucket + ':' + clientIp;
    }

    /**
     * Resolves the caller's address from a request, preferring the first hop of X-Forwarded-For (the deployment
     * sits behind a reverse proxy) and falling back to the socket's remote address.
     */
    public static String clientIp(HttpServletRequest request) {
        String forwardedFor = request.getHeader("X-Forwarded-For");
        if (forwardedFor != null && !forwardedFor.isBlank()) {
            return forwardedFor.split(",")[0].strip();
        }
        return request.getRemoteAddr();
    }
}
