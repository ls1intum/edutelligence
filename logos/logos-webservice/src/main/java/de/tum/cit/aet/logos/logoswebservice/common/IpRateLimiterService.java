package de.tum.cit.aet.logos.logoswebservice.common;

import java.time.Duration;
import java.util.ArrayDeque;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
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
 * budget. {@link #tryReserveAuthFailureSlot} atomically checks the budget and reserves a slot in the same
 * operation (Tomcat handles requests on a pool of threads, so a plain check-then-record pair would let a burst
 * of concurrent requests all observe the same free slot before any of them records a failure); the caller then
 * gives the slot back via {@link #releaseAuthFailureSlot} once authentication turns out to have succeeded, so
 * traffic that keeps authenticating successfully never approaches the limit. Callers must release the
 * reservation as soon as the key is known valid — before any slower downstream work — so that work in flight
 * cannot itself hold slots that would otherwise be available to other valid callers.</li>
 * </ul>
 *
 * <p>
 * State is process-local. logos-webservice runs as a single instance, so this needs no distributed backing store;
 * if that ever changes, this is the place to swap in a shared store (e.g. Redis) behind the same interface.
 *
 * <p>
 * Both categories key their window by source address, and {@code /info} takes no credential, so distinct callers
 * accumulate map entries for as long as the process runs. {@link #evictStaleWindows} sweeps those away on a
 * schedule so the map stays bounded by recently-active clients rather than growing forever.
 */
@Service
public class IpRateLimiterService {

    private static final Duration DEFAULT_WINDOW = Duration.ofMinutes(1);

    /**
     * How often {@link #evictStaleWindows} runs, in milliseconds ({@code @Scheduled} needs a compile-time
     * constant). Longer than the rate-limit window so that, by the time a sweep runs, a window with no recent
     * activity is guaranteed to have nothing left to prune — this is what lets the sweep tell "idle" apart from
     * "still active" without tracking last-access time separately.
     */
    private static final long SWEEP_INTERVAL_MS = 5 * 60 * 1000;

    private final RateLimitingProperties properties;

    private final Duration window;

    private final ConcurrentHashMap<String, ArrayDeque<Long>> requestWindows = new ConcurrentHashMap<>();

    @Autowired
    public IpRateLimiterService(RateLimitingProperties properties) {
        this(properties, DEFAULT_WINDOW);
    }

    /** Package-private: lets tests use a short window so real-time expiry can be observed without sleeping a minute. */
    IpRateLimiterService(RateLimitingProperties properties, Duration window) {
        this.properties = properties;
        this.window = window;
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
            throw new RateLimitExceededException(window.toSeconds());
        }
    }

    /**
     * Atomically checks {@code clientIp}'s authentication-failure budget and, if any remains, reserves one slot
     * from it in the same operation — so concurrent callers cannot all observe the same free slot the way a
     * separate check-then-record pair would. Call before attempting authentication.
     *
     * <p>
     * The reservation must be resolved afterward: give it back with {@link #releaseAuthFailureSlot} the moment
     * authentication is known to have succeeded — before any slower work that depends on it — so that work
     * cannot itself hold a slot other valid callers need. Leave it in place — do nothing — if authentication
     * fails; the reservation already counts as the spent unit.
     *
     * @return true if a slot was reserved (or the limiter is disabled/unlimited), false if the budget is exhausted
     */
    public boolean tryReserveAuthFailureSlot(String clientIp) {
        if (!properties.enabled() || properties.authFailureRequestsPerMinute() <= 0 || clientIp == null) {
            return true;
        }
        return tryConsume(key(clientIp, "auth_fail"), properties.authFailureRequestsPerMinute());
    }

    /** Gives back a slot reserved by {@link #tryReserveAuthFailureSlot}, once authentication succeeded after all. */
    public void releaseAuthFailureSlot(String clientIp) {
        if (!properties.enabled() || properties.authFailureRequestsPerMinute() <= 0 || clientIp == null) {
            return;
        }
        // computeIfPresent: a reservation always created the window first, so there is normally always one to
        // release into; if it were ever already gone (e.g. an unexpected double release) there is nothing to
        // give back, and creating a fresh window here would fabricate budget rather than restore it.
        requestWindows.computeIfPresent(key(clientIp, "auth_fail"), (k, deque) -> {
            // Any entry may be released, not necessarily the one this caller's own reservation added: every
            // entry in the window is fungible for counting purposes, so removing one restores the budget by
            // exactly the unit this caller is giving back, regardless of which concurrent reservation it was.
            deque.pollLast();
            return deque.isEmpty() ? null : deque;
        });
    }

    private boolean tryConsume(String key, int limit) {
        // compute() runs the remapping function atomically per key (ConcurrentHashMap locks the bin for its
        // duration), so the prune-check-add sequence below needs no separate lock the way a plain
        // computeIfAbsent + synchronized(window) pair would.
        boolean[] admitted = {false};
        requestWindows.compute(key, (k, existing) -> {
            ArrayDeque<Long> deque = existing != null ? existing : new ArrayDeque<>();
            prune(deque);
            if (deque.size() >= limit) {
                admitted[0] = false;
            } else {
                deque.addLast(System.nanoTime());
                admitted[0] = true;
            }
            return deque;
        });
        return admitted[0];
    }

    private void prune(ArrayDeque<Long> deque) {
        long cutoff = System.nanoTime() - window.toNanos();
        while (!deque.isEmpty() && deque.peekFirst() < cutoff) {
            deque.pollFirst();
        }
    }

    private static String key(String clientIp, String bucket) {
        return bucket + ':' + clientIp;
    }

    /**
     * Evicts windows that pruning alone never reaches: {@link #prune} only runs when a key is looked up again, so
     * a client that stops sending requests — the common case for {@code /info}, unauthenticated and therefore
     * queried by a constantly-changing set of source addresses — would otherwise sit in the map for the life of
     * the process. Running less often than {@link #SWEEP_INTERVAL_MS} guarantees any window with nothing added
     * since the last sweep has pruned down to empty by the time this runs, so "empty after pruning" is a safe
     * proxy for "idle" without tracking last-access time separately.
     */
    @Scheduled(initialDelay = SWEEP_INTERVAL_MS, fixedDelay = SWEEP_INTERVAL_MS)
    public void evictStaleWindows() {
        requestWindows.forEach((key, ignored) -> requestWindows.computeIfPresent(key, (k, deque) -> {
            prune(deque);
            return deque.isEmpty() ? null : deque;
        }));
    }

    /** Number of per-IP+bucket windows currently tracked. Exposed for tests observing memory bounds. */
    int trackedWindowCount() {
        return requestWindows.size();
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
