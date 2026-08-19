package de.tum.cit.aet.logos.logoswebservice.identity.service;

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
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorModelWindowClient;

@Service
public class MeKeysService {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final TypeReference<Object> OBJ_TYPE = new TypeReference<>() {};

    private final ApiKeyRepository apiKeyRepository;
    private final OrchestratorModelWindowClient modelWindowClient;

    public MeKeysService(ApiKeyRepository apiKeyRepository, OrchestratorModelWindowClient modelWindowClient) {
        this.apiKeyRepository = apiKeyRepository;
        this.modelWindowClient = modelWindowClient;
    }

    public List<Map<String, Object>> getKeysForUser(int userId) {
        return apiKeyRepository.findKeysForUser(userId).stream()
            .map(this::toMap)
            .toList();
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
        Map<String, Integer> windows = modelWindowClient.getContextWindows();
        return Optional.of(rows.stream()
            .map(r -> new ModelAccessDTO(
                r.getModelName(),
                includeProviderNames ? r.getProviderName() : null,
                r.getProviderType(),
                windows.get(r.getModelName())))
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

    private Map<String, Object> toMap(MyKeyProjection p) {
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

        Map<String, Object> team = new LinkedHashMap<>();
        team.put("id", p.getTeamId());
        team.put("name", p.getTeamName());
        team.put("team_monthly_budget_micro_cents", p.getTeamMonthlyBudgetMicroCents());
        team.put("budget_used_micro_cents", p.getTeamBudgetUsedMicroCents());
        m.put("team", team);
        return m;
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
        int lastDash = currentKeyValue.lastIndexOf('-');
        String prefix = lastDash > 0 ? currentKeyValue.substring(0, lastDash) : "lg";
        return prefix + "-" + ApiKeyFactory.generateToken();
    }
}
