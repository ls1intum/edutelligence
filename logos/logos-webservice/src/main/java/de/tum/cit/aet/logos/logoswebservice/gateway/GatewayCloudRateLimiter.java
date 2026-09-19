package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Per-key cloud RPM/TPM admission for the direct-cloud path.
 *
 * <p>Mirrors the orchestrator's {@code InMemoryRateLimiter} window (60s) and
 * the resolution order in {@code main.py}: key {@code cloud_*_limit}, then
 * generic {@code rpm_limit}/{@code tpm_limit}, then team defaults.
 *
 * <p>Process-local: multi-instance deployments enforce per replica (same as
 * the orchestrator's in-memory limiter). Traefik remains the cluster-wide
 * brake.
 */
@Service
public class GatewayCloudRateLimiter {

    /** Keep in sync with {@code RateLimitConfig.window_seconds} / MeKeysService. */
    static final int WINDOW_SECONDS = 60;

    private final ObjectMapper objectMapper;
    private final GatewayDeploymentRepository deploymentRepository;
    private final ConcurrentHashMap<String, Deque<Long>> requestWindows = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, Deque<long[]>> tokenWindows = new ConcurrentHashMap<>();

    public GatewayCloudRateLimiter(ObjectMapper objectMapper, GatewayDeploymentRepository deploymentRepository) {
        this.objectMapper = objectMapper;
        this.deploymentRepository = deploymentRepository;
    }

    /**
     * Admit a direct-cloud request or throw 429.
     *
     * @return estimated tokens recorded for this admission (for later TPM accounting)
     */
    public int enforceAndRecord(GatewayKey key, byte[] body) {
        Limits limits = resolveLimits(key);
        if (limits.rpm() == null && limits.tpm() == null) {
            return 0;
        }
        int estimatedTokens = estimateTokens(body);
        String bucket = "cloud:" + key.id();
        long now = System.currentTimeMillis();
        long cutoff = now - WINDOW_SECONDS * 1000L;

        synchronized (this) {
            if (limits.tpm() != null) {
                Deque<long[]> tok = tokenWindows.computeIfAbsent(bucket, k -> new ArrayDeque<>());
                pruneTokens(tok, cutoff);
                long total = 0;
                for (long[] entry : tok) {
                    total += entry[1];
                }
                if (total >= limits.tpm()) {
                    throw new ResponseStatusException(
                        HttpStatus.TOO_MANY_REQUESTS,
                        "TPM limit reached (" + limits.tpm() + "/" + WINDOW_SECONDS + "s)");
                }
            }
            if (limits.rpm() != null) {
                Deque<Long> req = requestWindows.computeIfAbsent(bucket, k -> new ArrayDeque<>());
                pruneRequests(req, cutoff);
                if (req.size() >= limits.rpm()) {
                    throw new ResponseStatusException(
                        HttpStatus.TOO_MANY_REQUESTS,
                        "RPM limit reached (" + limits.rpm() + "/" + WINDOW_SECONDS + "s)");
                }
                req.addLast(now);
            }
            if (limits.tpm() != null && estimatedTokens > 0) {
                Deque<long[]> tok = tokenWindows.computeIfAbsent(bucket, k -> new ArrayDeque<>());
                tok.addLast(new long[] {now, estimatedTokens});
            }
        }
        return estimatedTokens;
    }

    private Limits resolveLimits(GatewayKey key) {
        Integer cloudRpm = null;
        Integer cloudTpm = null;
        Integer genericRpm = null;
        Integer genericTpm = null;
        JsonNode settings = parseSettings(key.settingsJson());
        if (settings != null && settings.isObject()) {
            cloudRpm = intOrNull(settings.get("cloud_rpm_limit"));
            cloudTpm = intOrNull(settings.get("cloud_tpm_limit"));
            genericRpm = intOrNull(settings.get("rpm_limit"));
            genericTpm = intOrNull(settings.get("tpm_limit"));
        }
        Integer teamCloudRpm = null;
        Integer teamCloudTpm = null;
        if (key.teamId() != null) {
            int[] team = deploymentRepository.findTeamCloudRateLimits(key.teamId());
            if (team != null) {
                teamCloudRpm = team[0] > 0 ? team[0] : null;
                teamCloudTpm = team[1] > 0 ? team[1] : null;
                // 0 / null from DB: treat missing as null; repository returns -1 for null
                if (team[0] < 0) {
                    teamCloudRpm = null;
                }
                if (team[1] < 0) {
                    teamCloudTpm = null;
                }
            }
        }
        Integer rpm = firstNonNull(cloudRpm, genericRpm, teamCloudRpm);
        Integer tpm = firstNonNull(cloudTpm, genericTpm, teamCloudTpm);
        return new Limits(rpm, tpm);
    }

    private JsonNode parseSettings(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readTree(json);
        } catch (Exception e) {
            return null;
        }
    }

    private static Integer intOrNull(JsonNode n) {
        if (n == null || n.isNull() || !n.isNumber()) {
            return null;
        }
        return n.intValue();
    }

    private static Integer firstNonNull(Integer... values) {
        for (Integer v : values) {
            if (v != null) {
                return v;
            }
        }
        return null;
    }

    /** Rough input-token estimate so TPM has something to admit against before usage lands. */
    static int estimateTokens(byte[] body) {
        if (body == null || body.length == 0) {
            return 0;
        }
        return Math.max(1, body.length / 4);
    }

    private static void pruneRequests(Deque<Long> dq, long cutoff) {
        while (!dq.isEmpty() && dq.peekFirst() < cutoff) {
            dq.removeFirst();
        }
    }

    private static void pruneTokens(Deque<long[]> dq, long cutoff) {
        while (!dq.isEmpty() && dq.peekFirst()[0] < cutoff) {
            dq.removeFirst();
        }
    }

    private record Limits(Integer rpm, Integer tpm) {
    }
}
