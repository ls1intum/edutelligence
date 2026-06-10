package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateAppKeyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateApiKeyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.LogLevel;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyWithBudgetProjection;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamMemberRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;

@Service
public class ApiKeyAdminService {

    private static final SecureRandom SECURE_RANDOM = new SecureRandom();
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private final ApiKeyRepository apiKeyRepository;
    private final TeamRepository teamRepository;
    private final TeamMemberRepository teamMemberRepository;

    public ApiKeyAdminService(ApiKeyRepository apiKeyRepository,
                              TeamRepository teamRepository,
                              TeamMemberRepository teamMemberRepository) {
        this.apiKeyRepository = apiKeyRepository;
        this.teamRepository = teamRepository;
        this.teamMemberRepository = teamMemberRepository;
    }

    public List<Map<String, Object>> getKeysForTeam(int teamId) {
        return apiKeyRepository.findKeysForTeam(teamId).stream()
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("id", p.getId());
                m.put("key_value", p.getKeyValue());
                m.put("name", p.getName());
                m.put("key_type", p.getKeyType());
                m.put("user_id", p.getUserId());
                m.put("environment", p.getEnvironment());
                m.put("log", p.getLog());
                m.put("settings", parseJson(p.getSettingsText()));
                m.put("default_priority", p.getDefaultPriority());
                m.put("is_active", p.getIsActive());
                m.put("use_custom_permissions", p.getUseCustomPermissions());
                m.put("used_micro_cents", p.getUsedMicroCents());
                return m;
            })
            .toList();
    }

    public Optional<Map<String, Object>> getKeyById(int keyId) {
        return apiKeyRepository.findById(keyId).map(k -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", k.getId());
            m.put("key_value", k.getKeyValue());
            m.put("name", k.getName());
            m.put("key_type", k.getKeyType() != null ? k.getKeyType().name() : null);
            m.put("team_id", k.getTeamId());
            m.put("user_id", k.getUserId());
            m.put("environment", k.getEnvironment());
            m.put("default_priority", k.getDefaultPriority());
            m.put("is_active", k.getIsActive());
            m.put("settings", parseJson(k.getSettings()));
            m.put("use_custom_permissions", k.getUseCustomPermissions());
            return m;
        });
    }

    public boolean isTeamOwner(int teamId, int userId) {
        return teamMemberRepository.isOwner(teamId, userId);
    }

    public boolean duplicateAppKeyExists(int teamId, String environment) {
        return apiKeyRepository.existsByTeamIdAndKeyTypeAndEnvironmentAndIsActive(
            teamId, ApiKeyType.application, environment, true);
    }

    @Transactional
    public Map<String, Object> createAppKey(int teamId, CreateAppKeyRequestDTO req) {
        String keyTypeName = req.keyType() != null ? req.keyType() : "application";
        String environment = req.environment() != null ? req.environment() : "-";
        String logName = req.log() != null ? req.log() : "BILLING";
        int defaultPriority = req.defaultPriority() != null ? req.defaultPriority() : 0;
        boolean useCustomPermissions = Boolean.TRUE.equals(req.useCustomPermissions());
        String settingsJson = req.settings() != null ? toJson(req.settings()) : "{}";

        String keyValue = generateKey(teamId, keyTypeName, environment);
        ApiKey newKey = new ApiKey();
        newKey.setKeyValue(keyValue);
        newKey.setName(req.name());
        newKey.setKeyType(ApiKeyType.valueOf(keyTypeName));
        newKey.setTeamId(teamId);
        newKey.setEnvironment(environment);
        newKey.setLog(LogLevel.valueOf(logName));
        newKey.setSettings(settingsJson);
        newKey.setDefaultPriority(defaultPriority);
        newKey.setIsActive(true);
        newKey.setUseCustomPermissions(useCustomPermissions);
        newKey = apiKeyRepository.save(newKey);
        return Map.of("result", "Application Key created",
                      "id", newKey.getId(),
                      "api_key", newKey.getKeyValue());
    }

    public Map<String, Object> setLog(int keyId, String level) {
        if (!"BILLING".equals(level) && !"FULL".equals(level)) {
            throw new IllegalArgumentException("set_log must be BILLING or FULL");
        }
        ApiKey k = apiKeyRepository.findById(keyId)
            .orElseThrow(() -> new IllegalArgumentException("API key not found: " + keyId));
        k.setLog(LogLevel.valueOf(level));
        apiKeyRepository.save(k);
        return Map.of("result", "Updated log level to " + level);
    }

    @Transactional
    public void deactivateKey(int keyId) {
        apiKeyRepository.findById(keyId).ifPresent(k -> {
            k.setIsActive(false);
            apiKeyRepository.save(k);
        });
    }

    @Transactional
    public Map<String, Object> updateKey(int keyId, UpdateApiKeyRequestDTO req) {
        ApiKey k = apiKeyRepository.findById(keyId)
            .orElseThrow(() -> new IllegalArgumentException("API key not found: " + keyId));
        Map<String, Object> settings = parseJsonToMap(k.getSettings());

        applyLimit(settings, "budget_limit_micro_cents", req.budgetLimitMicroCents());
        applyLimit(settings, "cloud_rpm_limit", req.cloudRpmLimit() != null ? req.cloudRpmLimit().longValue() : null);
        applyLimit(settings, "cloud_tpm_limit", req.cloudTpmLimit() != null ? req.cloudTpmLimit().longValue() : null);
        applyLimit(settings, "local_rpm_limit", req.localRpmLimit() != null ? req.localRpmLimit().longValue() : null);
        applyLimit(settings, "local_tpm_limit", req.localTpmLimit() != null ? req.localTpmLimit().longValue() : null);

        k.setSettings(toJson(settings));
        if (req.environment() != null) k.setEnvironment(req.environment());
        if (req.defaultPriority() != null) k.setDefaultPriority(req.defaultPriority());
        if (req.log() != null) k.setLog(LogLevel.valueOf(req.log()));
        if (req.useCustomPermissions() != null) k.setUseCustomPermissions(req.useCustomPermissions());
        apiKeyRepository.save(k);
        return Map.of("result", "API Key updated successfully");
    }

    private String generateKey(int teamId, String keyType, String environment) {
        List<String> parts = new ArrayList<>();
        teamRepository.findById(teamId).ifPresent(t -> {
            if (t.getName() != null) parts.add(t.getName().toLowerCase());
        });
        if (parts.isEmpty()) parts.add("noteam");

        if ("application".equals(keyType) && environment != null && !environment.isBlank() && !"-".equals(environment)) {
            parts.add(environment.toLowerCase());
        }

        String label = String.join("-", parts)
            .replaceAll("[^a-z0-9\\-]", "-")
            .replaceAll("\\-+", "-")
            .replaceAll("^\\-|\\-$", "");
        if (label.length() > 35) label = label.substring(0, 35);

        byte[] bytes = new byte[96];
        SECURE_RANDOM.nextBytes(bytes);
        String token = java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        return "lg-" + label + "-" + token;
    }

    private void applyLimit(Map<String, Object> settings, String key, Long value) {
        if (value == null) return;
        if (value == -1L) settings.remove(key);
        else settings.put(key, value);
    }

    private Map<String, Object> parseJsonToMap(String json) {
        if (json == null || json.isBlank()) return new HashMap<>();
        try { return OBJECT_MAPPER.readValue(json, MAP_TYPE); }
        catch (Exception e) { return new HashMap<>(); }
    }

    private Object parseJson(String json) {
        if (json == null) return null;
        try { return OBJECT_MAPPER.readValue(json, Object.class); }
        catch (Exception e) { return json; }
    }

    private String toJson(Object obj) {
        if (obj == null) return null;
        try { return OBJECT_MAPPER.writeValueAsString(obj); }
        catch (Exception e) { return "{}"; }
    }
}
