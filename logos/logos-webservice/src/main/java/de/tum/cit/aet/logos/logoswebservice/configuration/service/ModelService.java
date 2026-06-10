package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelWithPriceProjection;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorNotificationService;

@Service
public class ModelService {

    private final ModelRepository modelRepository;
    private final ModelWeightService weightService;
    private final OrchestratorNotificationService orchestratorNotificationService;

    public ModelService(ModelRepository modelRepository, ModelWeightService weightService,
                        OrchestratorNotificationService orchestratorNotificationService) {
        this.modelRepository = modelRepository;
        this.weightService = weightService;
        this.orchestratorNotificationService = orchestratorNotificationService;
    }

    public List<Map<String, Object>> getModels(AuthContext auth) {
        List<ModelWithPriceProjection> projections = isAdmin(auth)
            ? modelRepository.findAllWithPricing()
            : modelRepository.findAllWithPricingForKey(auth.keyValue());
        return projections.stream().map(ModelService::toModelMap).toList();
    }

    @Transactional
    public Map<String, Object> addModel(AddModelRequestDTO req) {
        Model model = new Model();
        model.setName(req.name());
        model.setTags(req.tags() != null ? req.tags() : "");
        model.setParallel(req.parallel() != null ? req.parallel() : 1);
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
        if (req.parallel() != null) model.setParallel(req.parallel());
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
            map.put("parallel", m.getParallel());
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

    private static boolean isAdmin(AuthContext auth) {
        return "logos_admin".equals(auth.role()) || "app_admin".equals(auth.role());
    }

    private static Map<String, Object> toModelMap(ModelWithPriceProjection p) {
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
        m.put("parallel", p.getParallel());
        m.put("description", p.getDescription());
        m.put("input_usd_per_million", p.getInputUsdPerMillion());
        m.put("output_usd_per_million", p.getOutputUsdPerMillion());
        return m;
    }
}
