package de.tum.cit.aet.logos.logoswebservice.common;

/**
 * Per-request phase timings, collected on the request thread and logged once by
 * {@link RequestTimingFilter} when the request leaves the filter chain.
 *
 * <p>The recording methods are static and no-ops outside a request (scheduled
 * jobs, async threads), so callers never need to know whether a timing is open.
 */
public final class RequestTiming {

    private static final ThreadLocal<RequestTiming> CURRENT = new ThreadLocal<>();

    long jwtDecodeNanos = -1;
    long authNanos = -1;
    boolean synced;
    long syncUserNanos = -1;
    long syncResolveNanos = -1;
    long syncLockNanos = -1;
    long syncWriteNanos = -1;
    int syncTeams = -1;
    long handlerStartNanos = -1;

    private RequestTiming() {
    }

    static RequestTiming open() {
        RequestTiming timing = new RequestTiming();
        CURRENT.set(timing);
        return timing;
    }

    static void close() {
        CURRENT.remove();
    }

    /** JWT signature check and validation, including a JWKS fetch when the key cache is cold. */
    public static void recordJwtDecode(long nanos) {
        RequestTiming timing = CURRENT.get();
        if (timing != null) timing.jwtDecodeNanos = Math.max(timing.jwtDecodeNanos, 0) + nanos;
    }

    /** Mapping the token onto a local user, and whether that needed a full Keycloak sync. */
    public static void recordAuth(long nanos, boolean synced) {
        RequestTiming timing = CURRENT.get();
        if (timing == null) return;
        timing.authNanos = nanos;
        timing.synced = synced;
    }

    /**
     * The phases of a Keycloak sync: looking up and saving the user row, resolving the claimed
     * teams, waiting for their row locks, writing keys and memberships.
     */
    public static void recordSync(long userNanos, long resolveNanos, long lockNanos, long writeNanos, int teams) {
        RequestTiming timing = CURRENT.get();
        if (timing == null) return;
        timing.syncUserNanos = userNanos;
        timing.syncResolveNanos = resolveNanos;
        timing.syncLockNanos = lockNanos;
        timing.syncWriteNanos = writeNanos;
        timing.syncTeams = teams;
    }

    /** Authentication is done and the controller is about to run. */
    public static void markHandlerStart() {
        RequestTiming timing = CURRENT.get();
        if (timing != null) timing.handlerStartNanos = System.nanoTime();
    }
}
