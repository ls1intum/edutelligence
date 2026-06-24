package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakRoleMapper;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Policy;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ThresholdLevel;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.PolicyProjection;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.PolicyRepository;

@Service
public class PolicyService {

    private final PolicyRepository policyRepository;

    public PolicyService(PolicyRepository policyRepository) {
        this.policyRepository = policyRepository;
    }

    public List<Map<String, Object>> getPolicies(String role, Integer userId) {
        if (KeycloakRoleMapper.LOGOS_ADMIN.equals(role)) {
            return policyRepository.findAllForAdmin().stream().map(this::toMap).toList();
        }
        if (userId == null) return List.of();
        return policyRepository.findAllForUser(userId).stream().map(this::toMap).toList();
    }

    @Transactional
    public Map<String, Object> addPolicy(String name, String description, String thresholdPrivacy,
                                          int thresholdLatency, int thresholdAccuracy,
                                          int thresholdCost, int thresholdQuality,
                                          int priority, String topic,
                                          Integer apiKeyId, Integer teamId) {
        Policy p = new Policy();
        p.setName(name);
        p.setDescription(description);
        p.setThresholdPrivacy(parseThresholdLevel(thresholdPrivacy));
        p.setThresholdLatency(thresholdLatency);
        p.setThresholdAccuracy(thresholdAccuracy);
        p.setThresholdCost(thresholdCost);
        p.setThresholdQuality(thresholdQuality);
        p.setPriority(priority);
        p.setTopic(topic);
        p.setApiKeyId(apiKeyId);
        p.setTeamId(teamId);
        p = policyRepository.save(p);
        return Map.of("result", "Created Policy", "policy-id", p.getId());
    }

    @Transactional
    public Map<String, Object> updatePolicy(int id, String name, String description,
                                             String thresholdPrivacy,
                                             int thresholdLatency, int thresholdAccuracy,
                                             int thresholdCost, int thresholdQuality,
                                             int priority, String topic,
                                             Integer apiKeyId, Integer teamId) {
        Policy p = policyRepository.findById(id)
            .orElseThrow(() -> new IllegalArgumentException("Policy not found: " + id));
        p.setName(name);
        p.setDescription(description);
        p.setThresholdPrivacy(parseThresholdLevel(thresholdPrivacy));
        p.setThresholdLatency(thresholdLatency);
        p.setThresholdAccuracy(thresholdAccuracy);
        p.setThresholdCost(thresholdCost);
        p.setThresholdQuality(thresholdQuality);
        p.setPriority(priority);
        p.setTopic(topic);
        p.setApiKeyId(apiKeyId);
        p.setTeamId(teamId);
        policyRepository.save(p);
        return Map.of("result", "Updated Policy");
    }

    @Transactional
    public Map<String, Object> deletePolicy(int id) {
        Policy p = policyRepository.findById(id)
            .orElseThrow(() -> new IllegalArgumentException("Policy not found: " + id));
        policyRepository.delete(p);
        return Map.of("result", "Deleted Policy");
    }

    public Optional<Map<String, Object>> getPolicy(int policyId, String role, Integer userId) {
        if (KeycloakRoleMapper.LOGOS_ADMIN.equals(role)) {
            return policyRepository.findByIdForAdmin(policyId).map(this::toMap);
        }
        if (userId == null) return Optional.empty();
        return policyRepository.findByIdForUser(policyId, userId).map(this::toMap);
    }

    private static ThresholdLevel parseThresholdLevel(String value) {
        try {
            return ThresholdLevel.valueOf(value);
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "Invalid threshold_privacy: '" + value + "'");
        }
    }

    private Map<String, Object> toMap(PolicyProjection p) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", p.getId());
        m.put("api_key_id", p.getApiKeyId());
        m.put("team_id", p.getTeamId());
        m.put("name", p.getName());
        m.put("description", p.getDescription());
        m.put("threshold_privacy", p.getThresholdPrivacy());
        m.put("threshold_latency", p.getThresholdLatency());
        m.put("threshold_accuracy", p.getThresholdAccuracy());
        m.put("threshold_cost", p.getThresholdCost());
        m.put("threshold_quality", p.getThresholdQuality());
        m.put("priority", p.getPriority());
        m.put("topic", p.getTopic());
        return m;
    }
}
