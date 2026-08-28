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
 */
@Component
public class PasskeyChallengeStore {

    private static final Duration CHALLENGE_TTL = Duration.ofMinutes(5);

    private final Map<String, Challenge> challenges = new ConcurrentHashMap<>();
    private final SecureRandom random = new SecureRandom();

    private record Challenge(int userId, Instant expiresAt) {}

    /** Issues a fresh challenge for the user and returns it base64url-encoded. */
    public String issue(int userId) {
        purgeExpired();
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        String challenge = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        challenges.put(challenge, new Challenge(userId, Instant.now().plus(CHALLENGE_TTL)));
        return challenge;
    }

    /**
     * Consumes a challenge: it must be known, unexpired, and issued for this
     * user. The challenge is removed, so it cannot be replayed.
     *
     * @throws IllegalArgumentException when any of the checks fails
     */
    public void consume(String challenge, int userId) {
        if (challenge == null || challenge.isBlank()) {
            throw new IllegalArgumentException("Missing registration challenge.");
        }
        Challenge stored = challenges.remove(challenge);
        if (stored == null || Instant.now().isAfter(stored.expiresAt())) {
            throw new IllegalArgumentException("Unknown or expired registration challenge.");
        }
        if (stored.userId() != userId) {
            throw new IllegalArgumentException("Registration challenge was issued for another user.");
        }
    }

    private void purgeExpired() {
        Instant now = Instant.now();
        challenges.values().removeIf(challenge -> now.isAfter(challenge.expiresAt()));
    }
}
