package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.ModelAccessDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.LogLevel;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ModelAccessProjection;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.MyKeyProjection;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.RateLimitUsageProjection;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorModelWindowClient;

@Service
public class MeKeysService {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final TypeReference<Object> OBJ_TYPE = new TypeReference<>() {};
    private static final int API_KEY_TOKEN_LENGTH = 128;

    /**
     * The sliding window the orchestrator's rate limiter enforces rpm/tpm
     * limits over; the usage numbers shown next to a limit must come from the
     * same window to be comparable to it.
     *
     * This is a copy of the default of {@code RateLimitConfig.window_seconds}
     * in {@code logos/logos-orchestrator/src/logos/rate_limiter.py} — the
     * orchestrator is the source of truth. Keep the two in sync; the test
     * {@code RateLimitWindowConsistencyTest} fails if they drift, and the
     * corresponding comment in rate_limiter.py points back here.
     */
    private static final int RATE_LIMIT_WINDOW_SECONDS = 60;

    private final ApiKeyRepository apiKeyRepository;
    private final OrchestratorModelWindowClient modelWindowClient;

    public MeKeysService(ApiKeyRepository apiKeyRepository, OrchestratorModelWindowClient modelWindowClient) {
        this.apiKeyRepository = apiKeyRepository;
        this.modelWindowClient = modelWindowClient;
    }

    public List<Map<String, Object>> getKeysForUser(int userId) {
        List<MyKeyProjection> keys = apiKeyRepository.findKeysForUser(userId);
        Map<Integer, RateLimitUsageProjection> usageByKey = findRateLimitUsage(userId);
        return keys.stream()
            .map(p -> toMap(p, usageByKey.get(p.getId())))
            .toList();
    }

    /**
     * Rate-limit usage of the user's active keys inside one rate-limiter
     * window (see {@link #RATE_LIMIT_WINDOW_SECONDS}), keyed by key id.
     * Keys with no traffic in the window are absent; the caller renders them
     * at zero.
     */
    private Map<Integer, RateLimitUsageProjection> findRateLimitUsage(int userId) {
        Timestamp since = Timestamp.from(Instant.now().minusSeconds(RATE_LIMIT_WINDOW_SECONDS));
        Map<Integer, RateLimitUsageProjection> byKey = new HashMap<>();
        for (RateLimitUsageProjection p : apiKeyRepository.findRateLimitUsageForUser(userId, since)) {
            byKey.put(p.getKeyId(), p);
        }
        return byKey;
    }

    @Transactional
    public Optional<Map<String, Object>> setLogForUser(int keyId, int userId, String level) {
        if (!"BILLING".equals(level) && !"FULL".equals(level)) {
            throw new IllegalArgumentException("log must be BILLING or FULL");
        }
        Optional<ApiKey> keyOpt = apiKeyRepository.findById(keyId);
        if (keyOpt.isEmpty()) {
            return Optional.empty();
        }
        ApiKey key = keyOpt.get();
        if (!key.getUserId().equals(userId)) {
            // Deliberately collapse "exists but not owned" into the same outcome as
            // "not found" so callers can return a uniform 404 and avoid key
            // enumeration.
            return Optional.empty();
        }
        key.setLog(LogLevel.valueOf(level));
        apiKeyRepository.save(key);
        return Optional.of(Map.of("result", "Log level updated to " + level));
    }

    public Optional<List<ModelAccessDTO>> getAccessibleModels(
            int keyId, int userId, boolean includeProviderNames) {
        Optional<ApiKey> keyOpt = apiKeyRepository.findById(keyId);
        if (keyOpt.isEmpty()) {
            return Optional.empty();
        }
        ApiKey key = keyOpt.get();
        if (!key.getUserId().equals(userId)) {
            return Optional.empty();
        }
        // A key's accessible models are resolved from its team or its custom
        // permissions. logos_admin keys are no longer special-cased: the list
        // reflects the key's real scoped access, like any other key.
        List<ModelAccessProjection> rows = Boolean.TRUE.equals(key.getUseCustomPermissions())
            ? apiKeyRepository.findAccessibleModelsByKey(keyId)
            : apiKeyRepository.findAccessibleModelsByTeam(key.getTeamId());
        Map<String, OrchestratorModelWindowClient.ModelContextWindows> windows =
            modelWindowClient.getContextWindows();
        return Optional.of(rows.stream()
            .map(r -> {
                var w = windows.get(r.getModelName());
                return new ModelAccessDTO(
                    r.getModelName(),
                    includeProviderNames ? r.getProviderName() : null,
                    r.getProviderType(),
                    w != null ? w.currentMin() : null,
                    w != null ? w.currentMax() : null,
                    w != null ? w.overall() : null);
            })
            .toList());
    }

    @Transactional
    public Optional<Map<String, Object>> rotateKeyForUser(int keyId, int userId) {
        Optional<ApiKey> keyOpt = apiKeyRepository.findById(keyId);
        if (keyOpt.isEmpty()) {
            return Optional.empty();
        }
        ApiKey key = keyOpt.get();
        if (!key.getUserId().equals(userId)) {
            return Optional.empty();
        }
        key.setKeyValue(rotateKeyValue(key.getKeyValue()));
        apiKeyRepository.save(key);
        return Optional.of(Map.of(
            "result", "API key rotated successfully",
            "api_key", key.getKeyValue()));
    }

    private Map<String, Object> toMap(MyKeyProjection p, RateLimitUsageProjection usage) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", p.getId());
        m.put("name", p.getName());
        m.put("key_value", p.getKeyValue());
        m.put("key_type", p.getKeyType());
        m.put("environment", p.getEnvironment());
        m.put("log", p.getLog());
        m.put("use_custom_permissions", p.getUseCustomPermissions());
        m.put("used_micro_cents", p.getUsedMicroCents());
        m.put("settings", resolvedSettings(p));
        m.put("last_used_at", p.getLastUsedAt() != null ? p.getLastUsedAt().toString() : null);
        m.put("rate_limit_usage", toRateLimitUsage(usage));

        Map<String, Object> team = new LinkedHashMap<>();
        team.put("id", p.getTeamId());
        team.put("name", p.getTeamName());
        team.put("team_monthly_budget_micro_cents", p.getTeamMonthlyBudgetMicroCents());
        team.put("budget_used_micro_cents", p.getTeamBudgetUsedMicroCents());
        m.put("team", team);
        return m;
    }

    private Map<String, Object> toRateLimitUsage(RateLimitUsageProjection usage) {
        Map<String, Object> u = new LinkedHashMap<>();
        u.put("window_seconds", RATE_LIMIT_WINDOW_SECONDS);
        u.put("cloud_requests", usage != null ? usage.getCloudRequests() : 0L);
        u.put("cloud_tokens", usage != null ? usage.getCloudTokens() : 0L);
        u.put("local_requests", usage != null ? usage.getLocalRequests() : 0L);
        u.put("local_tokens", usage != null ? usage.getLocalTokens() : 0L);
        return u;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> resolvedSettings(MyKeyProjection p) {
        Map<String, Object> settings = new LinkedHashMap<>();
        // Start from the raw key settings JSON (may be null/empty).
        Object parsed = parseJson(p.getSettingsText());
        if (parsed instanceof Map<?, ?> raw) {
            settings.putAll((Map<String, Object>) raw);
        }
        // Fill in team defaults for any limit that the key did not override.
        settings.putIfAbsent("cloud_rpm_limit", p.getTeamDefaultCloudRpmLimit());
        settings.putIfAbsent("cloud_tpm_limit", p.getTeamDefaultCloudTpmLimit());
        settings.putIfAbsent("local_rpm_limit", p.getTeamDefaultLocalRpmLimit());
        settings.putIfAbsent("local_tpm_limit", p.getTeamDefaultLocalTpmLimit());
        settings.putIfAbsent("budget_limit_micro_cents", p.getTeamDefaultMonthlyBudgetMicroCents());
        return settings;
    }

    private Object parseJson(String json) {
        if (json == null || json.isBlank()) return Map.of();
        try { return OBJECT_MAPPER.readValue(json, OBJ_TYPE); }
        catch (Exception e) { return Map.of(); }
    }

    private String rotateKeyValue(String currentKeyValue) {
        if (currentKeyValue == null || currentKeyValue.isBlank()) {
            return "lg-" + ApiKeyFactory.generateToken();
        }
        String prefix = null;
        int separatorIndex = currentKeyValue.length() - API_KEY_TOKEN_LENGTH - 1;
        if (separatorIndex >= 0 && currentKeyValue.charAt(separatorIndex) == '-') {
            prefix = currentKeyValue.substring(0, separatorIndex);
        }
        if (prefix == null || prefix.isBlank()) {
            prefix = "lg";
        }
        return prefix + "-" + ApiKeyFactory.generateToken();
    }
}
