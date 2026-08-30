package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.time.Duration;
import java.time.Instant;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Component;

/**
 * In-memory store for WebAuthn registration challenges (#694). A challenge is
 * bound to the user it was issued for and valid for a few minutes; it is
 * consumed exactly once by the matching registration request. The webservice
 * runs as a single replica (see the docker compose files), so an in-memory
 * store is sufficient — a registration attempt that lands on a restart simply
 * gets a fresh challenge via a new /options call.
 *
 * <p>Outstanding challenges are capped per user ({@link
 * #MAX_OUTSTANDING_PER_USER}): issuing a new one evicts the user's oldest, so
 * repeatedly calling /options cannot grow the store without bound.
 */
@Component
public class PasskeyChallengeStore {

    private static final Duration CHALLENGE_TTL = Duration.ofMinutes(5);
    private static final int MAX_OUTSTANDING_PER_USER = 5;

    private final Map<String, Challenge> challenges = new ConcurrentHashMap<>();
    private final SecureRandom random = new SecureRandom();

    private record Challenge(int userId, Instant issuedAt, Instant expiresAt) {}

    /** Issues a fresh challenge for the user and returns it base64url-encoded. */
    public String issue(int userId) {
        purgeExpired();
        // Keep the per-user outstanding count under the cap: the user's own
        // oldest challenge is evicted first — a newer /options supersedes an
        // abandoned registration, which simply requests a fresh challenge.
        int count = 0;
        String oldestKey = null;
        Instant oldestIssued = null;
        for (Map.Entry<String, Challenge> entry : challenges.entrySet()) {
            Challenge challenge = entry.getValue();
            if (challenge.userId() != userId) {
                continue;
            }
            count++;
            if (oldestIssued == null || challenge.issuedAt().isBefore(oldestIssued)) {
                oldestIssued = challenge.issuedAt();
                oldestKey = entry.getKey();
            }
        }
        if (count >= MAX_OUTSTANDING_PER_USER && oldestKey != null) {
            challenges.remove(oldestKey);
        }
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        String challenge = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        Instant now = Instant.now();
        challenges.put(challenge, new Challenge(userId, now, now.plus(CHALLENGE_TTL)));
        return challenge;
    }

    /**
     * Consumes a challenge: it must be known, unexpired, and issued for this
     * user. The challenge is removed only after all checks pass, so a
     * rejected request (unknown challenge, or one issued to another user)
     * never invalidates a challenge whose owner still has it in flight.
     *
     * @throws IllegalArgumentException when any of the checks fails
     */
    public void consume(String challenge, int userId) {
        if (challenge == null || challenge.isBlank()) {
            throw new IllegalArgumentException("Missing registration challenge.");
        }
        Challenge stored = challenges.get(challenge);
        // One message for "unknown" and "issued to someone else": a specific
        // ownership error would let a caller enumerate challenges it did not
        // request.
        if (stored == null || stored.userId() != userId) {
            throw new IllegalArgumentException("Unknown or expired registration challenge.");
        }
        if (Instant.now().isAfter(stored.expiresAt())) {
            challenges.remove(challenge, stored);
            throw new IllegalArgumentException("Unknown or expired registration challenge.");
        }
        // Conditional remove: if a concurrent request already consumed the
        // challenge, this one fails instead of double-creating the credential.
        if (!challenges.remove(challenge, stored)) {
            throw new IllegalArgumentException("Unknown or expired registration challenge.");
        }
    }

    private void purgeExpired() {
        Instant now = Instant.now();
        challenges.values().removeIf(challenge -> now.isAfter(challenge.expiresAt()));
    }
}
