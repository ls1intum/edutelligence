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

@Service
public class MeKeysService {

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final TypeReference<Object> OBJ_TYPE = new TypeReference<>() {};

    private final ApiKeyRepository apiKeyRepository;

    public MeKeysService(ApiKeyRepository apiKeyRepository) {
        this.apiKeyRepository = apiKeyRepository;
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

    public Optional<List<ModelAccessDTO>> getAccessibleModels(int keyId, int userId, String role) {
        Optional<ApiKey> keyOpt = apiKeyRepository.findById(keyId);
        if (keyOpt.isEmpty()) {
            return Optional.empty();
        }
        ApiKey key = keyOpt.get();
        if (!key.getUserId().equals(userId)) {
            return Optional.empty();
        }
        List<ModelAccessProjection> rows;
        if ("logos_admin".equals(role)) {
            rows = apiKeyRepository.findAllModels();
        } else {
            rows = Boolean.TRUE.equals(key.getUseCustomPermissions())
                ? apiKeyRepository.findAccessibleModelsByKey(keyId)
                : apiKeyRepository.findAccessibleModelsByTeam(key.getTeamId());
        }
        return Optional.of(rows.stream()
            .map(r -> new ModelAccessDTO(r.getModelName(), r.getProviderName(), r.getProviderType()))
            .toList());
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
        m.put("settings", parseJson(p.getSettingsText()));
        m.put("last_used_at", p.getLastUsedAt() != null ? p.getLastUsedAt().toString() : null);

        Map<String, Object> team = new LinkedHashMap<>();
        team.put("id", p.getTeamId());
        team.put("name", p.getTeamName());
        team.put("team_monthly_budget_micro_cents", p.getTeamMonthlyBudgetMicroCents());
        team.put("budget_used_micro_cents", p.getTeamBudgetUsedMicroCents());
        m.put("team", team);
        return m;
    }

    private Object parseJson(String json) {
        if (json == null || json.isBlank()) return Map.of();
        try { return OBJECT_MAPPER.readValue(json, OBJ_TYPE); }
        catch (Exception e) { return Map.of(); }
    }
}
