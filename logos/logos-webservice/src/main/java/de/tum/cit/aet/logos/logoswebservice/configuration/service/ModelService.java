package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ModelCapabilitiesDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelCapabilities;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelCapabilitiesRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelWithPriceProjection;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ModelAccessProjection;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorModelHealthClient;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorNotificationService;

@Service
public class ModelService {

    private final ModelRepository modelRepository;
    private final ModelWeightService weightService;
    private final OrchestratorNotificationService orchestratorNotificationService;
    private final ModelCapabilitiesRepository modelCapabilitiesRepository;
    private final OrchestratorModelHealthClient orchestratorModelHealthClient;
    private final ApiKeyRepository apiKeyRepository;

    public ModelService(ModelRepository modelRepository, ModelWeightService weightService,
                        OrchestratorNotificationService orchestratorNotificationService, ModelCapabilitiesRepository modelCapabilitiesRepository,
                        OrchestratorModelHealthClient orchestratorModelHealthClient, ApiKeyRepository apiKeyRepository) {
        this.modelRepository = modelRepository;
        this.weightService = weightService;
        this.orchestratorNotificationService = orchestratorNotificationService;
        this.modelCapabilitiesRepository = modelCapabilitiesRepository;
        this.orchestratorModelHealthClient = orchestratorModelHealthClient;
        this.apiKeyRepository = apiKeyRepository;
    }

    public List<Map<String, Object>> getModels(AuthContext auth) {
        // last_used_at is a platform-wide usage figure, so it is only exposed to
        // Logos admins; everyone else gets the same list without that field.
        boolean includeLastUsed = isLogosAdmin(auth);
        List<ModelWithPriceProjection> projections = includeLastUsed
            ? modelRepository.findAllWithPricing()
            : modelRepository.findAllWithPricingForUser(auth.userId());
        return projections.stream().map(p -> toModelMap(p, includeLastUsed)).toList();
    }

    /**
     * Current health of every model the given API key may access, as computed
     * live by the orchestrator from its worker registry. Applications use this
     * to check before sending traffic whether a model has a healthy/available
     * deployment right now. Access follows the key's permissions exactly as
     * the orchestrator resolves them for requests: the key's own model
     * permissions when it uses custom permissions, otherwise its team's.
     * Returns empty when the key is unknown or inactive.
     */
    public Optional<Map<String, Object>> getModelHealth(String keyValue) {
        ApiKey key = apiKeyRepository.findByKeyValueAndIsActiveTrue(keyValue).orElse(null);
        if (key == null) {
            return Optional.empty();
        }
        Set<String> accessibleModels;
        if (Boolean.TRUE.equals(key.getUseCustomPermissions())) {
            accessibleModels = apiKeyRepository.findAccessibleModelsByKey(key.getId()).stream()
                .map(ModelAccessProjection::getModelName)
                .collect(Collectors.toSet());
        } else if (key.getTeamId() != null) {
            accessibleModels = apiKeyRepository.findAccessibleModelsByTeam(key.getTeamId()).stream()
                .map(ModelAccessProjection::getModelName)
                .collect(Collectors.toSet());
        } else {
            accessibleModels = Set.of();
        }
        List<Map<String, Object>> visible = orchestratorModelHealthClient.getModelHealth().stream()
            .filter(entry -> accessibleModels.contains(entry.get("name")))
            .toList();
        return Optional.of(Map.of("models", visible));
    }

    @Transactional
    public Map<String, Object> addModel(AddModelRequestDTO req) {
        Model model = new Model();
        model.setName(req.name());
        model.setTags(req.tags() != null ? req.tags() : "");
        model.setDescription(req.description() != null ? req.description() : "");
        model.setWeightLatency(0);
        model.setWeightAccuracy(0);
        model.setWeightCost(0);
        model.setWeightQuality(0);
        model = modelRepository.save(model);
        weightService.rebalanceAfterAdd(
            model.getId(),
            req.worseLatencyId(), req.worseAccuracyId(),
            req.worseCostId(), req.worseQualityId()
        );
        orchestratorNotificationService.notifyRefresh(true);
        return Map.of("result", "Created Model", "model_id", model.getId());
    }

    @Transactional
    public Map<String, Object> updateModelInfo(UpdateModelRequestDTO req) {
        Model model = modelRepository.findById(req.modelId())
            .orElseThrow(() -> new IllegalArgumentException("Model not found: " + req.modelId()));
        if (req.name() != null) model.setName(req.name());
        if (req.description() != null) model.setDescription(req.description());
        if (req.tags() != null) model.setTags(req.tags());
        if (req.weightLatency() != null) model.setWeightLatency(req.weightLatency());
        if (req.weightAccuracy() != null) model.setWeightAccuracy(req.weightAccuracy());
        if (req.weightCost() != null) model.setWeightCost(req.weightCost());
        if (req.weightQuality() != null) model.setWeightQuality(req.weightQuality());
        modelRepository.save(model);
        orchestratorNotificationService.notifyRefresh(true);
        return Map.of("result", "Model updated");
    }

    @Transactional
    public Map<String, Object> deleteModel(Integer id) {
        if (!modelRepository.existsById(id)) {
            throw new IllegalArgumentException("Model not found: " + id);
        }
        weightService.rebalanceAfterDelete(id);
        orchestratorNotificationService.notifyRefresh(true);
        return Map.of("result", "Deleted Model");
    }

    public Optional<Map<String, Object>> getModel(Integer id) {
        return modelRepository.findById(id).map(m -> {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("id", m.getId());
            map.put("name", m.getName() != null ? m.getName() : "Model " + m.getId());
            map.put("weight_latency", m.getWeightLatency());
            map.put("weight_accuracy", m.getWeightAccuracy());
            map.put("weight_cost", m.getWeightCost());
            map.put("weight_quality", m.getWeightQuality());
            map.put("tags", m.getTags());
            map.put("description", m.getDescription());
            return map;
        });
    }

    @Transactional
    public Map<String, Object> updateModelWeight(int id, String category, int feedback) {
        if (!modelRepository.existsById(id)) {
            throw new IllegalArgumentException("Model not found: " + id);
        }
        weightService.rebalanceAfterFeedback(id, category, feedback);
        return Map.of("result", "Updated Model");
    }

    public Map<String, Object> getGeneralModelStats() {
        return Map.of("totalModels", modelRepository.count());
    }

    private static boolean isLogosAdmin(AuthContext auth) {
        return Role.LOGOS_ADMIN.matches(auth.role());
    }

    private static Map<String, Object> toModelMap(ModelWithPriceProjection p, boolean includeLastUsed) {
        Map<String, Object> m = new LinkedHashMap<>();
        int id = p.getId();
        String name = p.getName();
        m.put("id", id);
        m.put("name", name != null ? name : "Model " + id);
        m.put("weight_latency", p.getWeightLatency());
        m.put("weight_accuracy", p.getWeightAccuracy());
        m.put("weight_cost", p.getWeightCost());
        m.put("weight_quality", p.getWeightQuality());
        m.put("tags", p.getTags());
        m.put("description", p.getDescription());
        m.put("input_usd_per_million", p.getInputUsdPerMillion());
        m.put("output_usd_per_million", p.getOutputUsdPerMillion());
        if (includeLastUsed) {
            m.put("last_used_at", p.getLastUsedAt() != null ? p.getLastUsedAt().toString() : null);
        }
        return m;
    }

    public Optional<ModelCapabilitiesDTO> getModelCapabilities(Integer modelId) {
        return modelCapabilitiesRepository.findByModelId(modelId)
            .map(ModelService::toModelCapabilitiesDTO);
    }

    public Map<Integer, ModelCapabilitiesDTO> getModelCapabilities(List<Integer> modelIds) {
        return modelCapabilitiesRepository.findByModelIdIn(modelIds)
            .stream()
            .map(ModelService::toModelCapabilitiesDTO)
            .collect(Collectors.toMap(
                ModelCapabilitiesDTO::modelId,
                Function.identity()
            ));
    }

    private static ModelCapabilitiesDTO toModelCapabilitiesDTO(ModelCapabilities capabilities) {
        return new ModelCapabilitiesDTO(
            capabilities.getModelId(),
            capabilities.getSupportsFunctionCalling(),
            capabilities.getSupportsVision(),
            capabilities.getSupportsReasoning()
        );
    }
}
