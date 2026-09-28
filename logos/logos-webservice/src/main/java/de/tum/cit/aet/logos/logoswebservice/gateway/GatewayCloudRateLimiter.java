package de.tum.cit.aet.logos.logoswebservice.gateway;

import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Per-key cloud RPM/TPM limit resolution for the direct-cloud path.
 *
 * <p>Mirrors the orchestrator's {@code InMemoryRateLimiter} window (60s) and
 * the resolution order in {@code main.py}: key {@code cloud_*_limit}, then
 * generic {@code rpm_limit}/{@code tpm_limit}, then team defaults.
 *
 * <p>Both <b>RPM</b> and <b>TPM</b> are enforced shared across webservice
 * replicas in {@link GatewayCloudAccounting#admitAndReserve}: recent
 * {@code gw-*} log rows are counted (RPM) and their
 * {@code gateway_estimated_tokens} summed (TPM). This class only resolves the
 * limits and estimates the tokens a request will consume before usage lands —
 * it holds no process-local admission state.
 */
@Service
public class GatewayCloudRateLimiter {

    /** Keep in sync with {@code RateLimitConfig.window_seconds} / MeKeysService. */
    static final int WINDOW_SECONDS = 60;

    private final ObjectMapper objectMapper;
    private final GatewayDeploymentRepository deploymentRepository;

    public GatewayCloudRateLimiter(ObjectMapper objectMapper, GatewayDeploymentRepository deploymentRepository) {
        this.objectMapper = objectMapper;
        this.deploymentRepository = deploymentRepository;
    }

    /** Resolved cloud RPM limit for shared (cross-replica) enforcement, or null. */
    public Integer cloudRpmLimit(GatewayKey key) {
        return resolveLimits(key).rpm();
    }

    /** Resolved cloud TPM limit for shared (cross-replica) enforcement, or null. */
    public Integer cloudTpmLimit(GatewayKey key) {
        return resolveLimits(key).tpm();
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

    private record Limits(Integer rpm, Integer tpm) {
    }
}
