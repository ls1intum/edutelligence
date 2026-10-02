package de.tum.cit.aet.logos.logoswebservice.common;

import java.net.InetAddress;
import java.net.UnknownHostException;
import java.time.Duration;
import java.util.ArrayDeque;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
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
 * <li>The failure path of API-key authentication (e.g. {@code /logosdb/get_model_health}) — only a completed
 * 401 spends budget. Pending lookups are tracked separately by {@link #tryReserveAuthFailureSlot}, then either
 * released via {@link #releaseAuthFailureSlot} for valid credentials or converted to a completed failure by
 * {@link #recordAuthFailureSlot}. This keeps valid concurrent requests outside the failure budget while the
 * completed-failure update remains atomic.</li>
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
    private final String trustedProxyCidrs;

    private final ConcurrentHashMap<String, ArrayDeque<Long>> requestWindows = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, Integer> pendingAuthRequests = new ConcurrentHashMap<>();

    public IpRateLimiterService(RateLimitingProperties properties) {
        this(properties, DEFAULT_WINDOW, "172.16.0.0/12");
    }

    @Autowired
    public IpRateLimiterService(
            RateLimitingProperties properties,
            @Value("${logos.rate-limiting.trusted-proxy-cidrs:172.16.0.0/12}") String trustedProxyCidrs) {
        this(properties, DEFAULT_WINDOW, trustedProxyCidrs);
    }

    /** Package-private: lets tests use a short window so real-time expiry can be observed without sleeping a minute. */
    IpRateLimiterService(RateLimitingProperties properties, Duration window) {
        this(properties, window, "172.16.0.0/12");
    }

    private IpRateLimiterService(RateLimitingProperties properties, Duration window, String trustedProxyCidrs) {
        this.properties = properties;
        this.window = window;
        this.trustedProxyCidrs = trustedProxyCidrs;
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
     * Tracks an authentication lookup that is in progress. The failure budget is
     * deliberately not checked here: valid concurrent requests must not be
     * rejected because other requests are still being authenticated or because
     * completed failures have filled the failure window.
     *
     * <p>
     * The reservation must be resolved afterward: give it back with {@link #releaseAuthFailureSlot} when
     * authentication succeeds, or convert it to a completed failure with {@link #recordAuthFailureSlot}.
     *
     * @return true if the lookup was tracked (or the limiter is disabled/unlimited)
     */
    public boolean tryReserveAuthFailureSlot(String clientIp) {
        if (!properties.enabled() || properties.authFailureRequestsPerMinute() <= 0 || clientIp == null) {
            return true;
        }
        pendingAuthRequests.merge(key(clientIp, "auth_fail"), 1, Integer::sum);
        return true;
    }

    /** Gives back a pending lookup reservation once authentication succeeded. */
    public void releaseAuthFailureSlot(String clientIp) {
        if (!properties.enabled() || properties.authFailureRequestsPerMinute() <= 0 || clientIp == null) {
            return;
        }
        releasePending(key(clientIp, "auth_fail"));
    }

    /**
     * Converts one pending lookup into a completed failure if the failure window has capacity.
     *
     * @return false when this completed failure is beyond the configured limit
     */
    public boolean recordAuthFailureSlot(String clientIp) {
        if (!properties.enabled() || properties.authFailureRequestsPerMinute() <= 0 || clientIp == null) {
            return true;
        }
        String key = key(clientIp, "auth_fail");
        boolean[] admitted = {false};
        requestWindows.compute(key, (k, existing) -> {
            ArrayDeque<Long> deque = existing != null ? existing : new ArrayDeque<>();
            prune(deque);
            if (deque.size() < properties.authFailureRequestsPerMinute()) {
                deque.addLast(System.nanoTime());
                admitted[0] = true;
            }
            return deque;
        });
        releasePending(key);
        return admitted[0];
    }

    private void releasePending(String key) {
        pendingAuthRequests.computeIfPresent(key, (k, pending) -> pending <= 1 ? null : pending - 1);
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

    /** Resolves the caller's address, trusting forwarded headers only from configured proxies. */
    public String clientIp(HttpServletRequest request) {
        String remoteAddr = request.getRemoteAddr();
        String forwardedFor = request.getHeader("X-Forwarded-For");
        if (isTrustedProxy(remoteAddr) && forwardedFor != null && !forwardedFor.isBlank()) {
            return forwardedFor.split(",")[0].strip();
        }
        return remoteAddr;
    }

    private boolean isTrustedProxy(String address) {
        if (address == null || trustedProxyCidrs == null) {
            return false;
        }
        for (String cidr : trustedProxyCidrs.split(",")) {
            if (addressInCidr(address, cidr.strip())) {
                return true;
            }
        }
        return false;
    }

    private static boolean addressInCidr(String address, String cidr) {
        try {
            int slash = cidr.indexOf('/');
            InetAddress candidate = InetAddress.getByName(address);
            InetAddress network = InetAddress.getByName(slash < 0 ? cidr : cidr.substring(0, slash));
            byte[] candidateBytes = candidate.getAddress();
            byte[] networkBytes = network.getAddress();
            if (candidateBytes.length != networkBytes.length) {
                return false;
            }
            int prefixBits = slash < 0 ? networkBytes.length * 8 : Integer.parseInt(cidr.substring(slash + 1));
            if (prefixBits < 0 || prefixBits > candidateBytes.length * 8) {
                return false;
            }
            int fullBytes = prefixBits / 8;
            int remainingBits = prefixBits % 8;
            for (int i = 0; i < fullBytes; i++) {
                if (candidateBytes[i] != networkBytes[i]) {
                    return false;
                }
            }
            return remainingBits == 0
                || (candidateBytes[fullBytes] & (0xFF << (8 - remainingBits)))
                    == (networkBytes[fullBytes] & (0xFF << (8 - remainingBits)));
        } catch (UnknownHostException | NumberFormatException e) {
            return false;
        }
    }
}
