package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.List;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
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
 * <p>Both <b>RPM</b> and <b>TPM</b> are enforced in Redis with a sliding
 * window shared by every webservice replica. Admission is a single Lua
 * script (prune → check → claim), so concurrent replicas cannot each pass
 * against the same totals. When no limit is configured the script is skipped.
 * When a limit is set and Redis is unreachable, admission fails closed (503).
 */
@Service
public class GatewayCloudRateLimiter {

    private static final Logger log = LoggerFactory.getLogger(GatewayCloudRateLimiter.class);

    /** Keep in sync with {@code RateLimitConfig.window_seconds} / MeKeysService. */
    static final int WINDOW_SECONDS = 60;

    private static final String ADMIT_SCRIPT = """
        local rpm_key = KEYS[1]
        local tpm_key = KEYS[2]
        -- Redis server time so skewed replica clocks cannot prune each other early.
        local redis_time = redis.call('TIME')
        local now = tonumber(redis_time[1]) * 1000 + math.floor(tonumber(redis_time[2]) / 1000)
        local window_ms = tonumber(ARGV[1])
        local rpm_limit = tonumber(ARGV[2])
        local tpm_limit = tonumber(ARGV[3])
        local tokens = tonumber(ARGV[4])
        local member = ARGV[5]
        local cutoff = now - window_ms

        redis.call('ZREMRANGEBYSCORE', rpm_key, '-inf', cutoff)
        redis.call('ZREMRANGEBYSCORE', tpm_key, '-inf', cutoff)

        if rpm_limit > 0 then
          local rpm = redis.call('ZCARD', rpm_key)
          if rpm >= rpm_limit then
            return 0
          end
        end

        if tpm_limit > 0 then
          local entries = redis.call('ZRANGE', tpm_key, 0, -1)
          local sum = 0
          for _, entry in ipairs(entries) do
            local sep = string.find(entry, ':', 1, true)
            if sep then
              sum = sum + tonumber(string.sub(entry, sep + 1))
            end
          end
          if sum + tokens > tpm_limit then
            return -1
          end
        end

        redis.call('ZADD', rpm_key, now, member)
        redis.call('ZADD', tpm_key, now, member .. ':' .. tokens)
        redis.call('PEXPIRE', rpm_key, window_ms)
        redis.call('PEXPIRE', tpm_key, window_ms)
        return 1
        """;

    private final ObjectMapper objectMapper;
    private final GatewayDeploymentRepository deploymentRepository;
    private final StringRedisTemplate redis;
    private final DefaultRedisScript<Long> admitScript;

    public GatewayCloudRateLimiter(
            ObjectMapper objectMapper,
            GatewayDeploymentRepository deploymentRepository,
            StringRedisTemplate redis) {
        this.objectMapper = objectMapper;
        this.deploymentRepository = deploymentRepository;
        this.redis = redis;
        this.admitScript = new DefaultRedisScript<>(ADMIT_SCRIPT, Long.class);
    }

    /**
     * Claim one request against the key's shared RPM/TPM window, or throw.
     *
     * <p>No-op when neither limit is configured. Atomic across replicas.
     */
    public void enforce(GatewayKey key, byte[] body) {
        Limits limits = resolveLimits(key);
        boolean checkRpm = limits.rpm() != null && limits.rpm() > 0;
        boolean checkTpm = limits.tpm() != null && limits.tpm() > 0;
        if (!checkRpm && !checkTpm) {
            return;
        }

        int estimatedTokens = estimateTokens(body);
        long windowMs = WINDOW_SECONDS * 1000L;
        String member = UUID.randomUUID().toString();
        String rpmKey = "gw:rpm:" + key.id();
        String tpmKey = "gw:tpm:" + key.id();

        Long result;
        try {
            result = redis.execute(
                admitScript,
                List.of(rpmKey, tpmKey),
                Long.toString(windowMs),
                Integer.toString(checkRpm ? limits.rpm() : 0),
                Integer.toString(checkTpm ? limits.tpm() : 0),
                Integer.toString(Math.max(0, estimatedTokens)),
                member);
        } catch (RuntimeException e) {
            log.error("Redis unavailable for cloud rate limit keyId={}", key.id(), e);
            throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "Rate limiter unavailable");
        }

        if (result == null) {
            throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE, "Rate limiter unavailable");
        }
        if (result == 0L) {
            throw new ResponseStatusException(
                HttpStatus.TOO_MANY_REQUESTS,
                "RPM limit reached (" + limits.rpm() + "/" + WINDOW_SECONDS + "s)");
        }
        if (result < 0L) {
            throw new ResponseStatusException(
                HttpStatus.TOO_MANY_REQUESTS,
                "TPM limit reached (" + limits.tpm() + "/" + WINDOW_SECONDS + "s)");
        }
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

    private record Limits(Integer rpm, Integer tpm) {
    }
}
