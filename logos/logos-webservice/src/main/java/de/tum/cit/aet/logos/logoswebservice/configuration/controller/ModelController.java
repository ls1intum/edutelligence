package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

import java.util.Locale;
import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DeleteModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.GetModelCapabilitiesRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.GetModelMetricsRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.GetModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateModelWeightRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelCapabilitiesUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorCalibrationLogsClient;

import jakarta.servlet.http.HttpServletRequest;

@RestController
@RequestMapping("/logosdb")
public class ModelController {

    private final ModelService modelService;
    private final PriceUpdaterService priceUpdaterService;
    private final ModelCapabilitiesUpdaterService modelCapabilitiesUpdaterService;
    private final OrchestratorCalibrationLogsClient orchestratorCalibrationLogsClient;

    public ModelController(ModelService modelService,
                           PriceUpdaterService priceUpdaterService,
                           ModelCapabilitiesUpdaterService modelCapabilitiesUpdaterService,
                           OrchestratorCalibrationLogsClient orchestratorCalibrationLogsClient) {
        this.modelService = modelService;
        this.priceUpdaterService = priceUpdaterService;
        this.modelCapabilitiesUpdaterService = modelCapabilitiesUpdaterService;
        this.orchestratorCalibrationLogsClient = orchestratorCalibrationLogsClient;
    }

    @PostMapping("/get_models")
    public ResponseEntity<?> getModels(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(modelService.getModels(auth));
    }

    /**
     * Model-level health for applications, authenticated with a Logos API key
     * (logos_key / logos-key header or Authorization: Bearer) — not a JWT —
     * because the callers are the applications that send inference traffic,
     * which hold API keys. Only models the key may access are reported.
     */
    @PostMapping("/get_model_health")
    public ResponseEntity<?> getModelHealth(HttpServletRequest request) {
        String apiKey = extractApiKey(request);
        if (apiKey == null) {
            return ResponseEntity.status(401).body(Map.of("detail", "Invalid or missing API key"));
        }
        return modelService.getModelHealth(apiKey)
            .map(ResponseEntity::ok)
            .orElseGet(() -> ResponseEntity.status(401).body(Map.of("detail", "Invalid or missing API key")));
    }

    static String extractApiKey(HttpServletRequest request) {
        String key = request.getHeader("logos_key");
        if (key == null || key.isBlank()) {
            key = request.getHeader("logos-key");
        }
        if (key == null || key.isBlank()) {
            String authorization = request.getHeader("Authorization");
            if (authorization != null && authorization.toLowerCase(Locale.ROOT).startsWith("bearer ")) {
                key = authorization.substring("bearer ".length());
            }
        }
        if (key == null) return null;
        key = key.strip();
        return key.isEmpty() ? null : key;
    }

    @PostMapping("/add_model")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> addModel(
            @RequestBody AddModelRequestDTO req) {
        Map<String, Object> serviceResult = modelService.addModel(req);
        Integer newModelId = (Integer) serviceResult.get("model_id");
        if (newModelId != null && req.name() != null) {
            priceUpdaterService.updatePricesForModelAsync(newModelId, req.name());
            modelCapabilitiesUpdaterService.updateCapabilitiesForModelAsync(
                newModelId,
                req.name()
            );
        }
        return ResponseEntity.ok(serviceResult);
    }

    @PostMapping("/update_model_info")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> updateModelInfo(
            @RequestBody UpdateModelRequestDTO req) {
        try {
            ResponseEntity<?> response = ResponseEntity.ok(modelService.updateModelInfo(req));
            if (req.name() != null) {
                priceUpdaterService.updatePricesForModelAsync(req.modelId(), req.name());
                modelCapabilitiesUpdaterService.updateCapabilitiesForModelAsync(req.modelId(), req.name());
            }
            return response;
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/delete_model")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> deleteModel(
            @RequestBody DeleteModelRequestDTO req) {
        if (req.id() == null) return ResponseEntity.badRequest().body(Map.of("error", "id is required"));
        try {
            return ResponseEntity.ok(modelService.deleteModel(req.id()));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/get_model")
    public ResponseEntity<?> getModel(
            @RequestBody GetModelRequestDTO req) {
        if (req.id() == null) return ResponseEntity.badRequest().body(Map.of("error", "id is required"));
        return modelService.getModel(req.id())
            .map(ResponseEntity::ok)
            .<ResponseEntity<?>>map(r -> r)
            .orElse(ResponseEntity.status(404).body(Map.of("error", "Model not found")));
    }

    @PostMapping("/get_model_calibration_logs")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> getModelCalibrationLogs(
            @RequestBody GetModelRequestDTO req) {
        if (req.id() == null) return ResponseEntity.badRequest().body(Map.of("error", "id is required"));
        return modelService.getModel(req.id())
            .map(model -> ResponseEntity.ok(
                Map.of("logs", orchestratorCalibrationLogsClient.getLogs((String) model.get("name")))))
            .<ResponseEntity<?>>map(r -> r)
            .orElse(ResponseEntity.status(404).body(Map.of("error", "Model not found")));
    }

    @PostMapping("/get_general_model_stats")
    public ResponseEntity<?> getGeneralModelStats() {
        return ResponseEntity.ok(modelService.getGeneralModelStats());
    }

    /**
     * Auto-derived L/A/C/Q metrics per model-provider pair (issue #651).
     * The optional model_id restricts the result to one model's pairs.
     */
    @PostMapping("/get_model_metrics")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> getModelMetrics(@RequestBody GetModelMetricsRequestDTO req) {
        return ResponseEntity.ok(modelService.getModelMetrics(req.modelId()));
    }

    @PostMapping("/update_model")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> updateModel(
            @RequestBody UpdateModelWeightRequestDTO req) {
        if (req.id() == null || req.category() == null || req.value() == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "id, category, and value are required"));
        }
        try {
            return ResponseEntity.ok(modelService.updateModelWeight(req.id(), req.category(), req.value()));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/get_model_capabilities")
    public ResponseEntity<?> getModelCapabilities(
            @RequestBody GetModelCapabilitiesRequestDTO req) {

        if (req.ids() == null || req.ids().isEmpty()) {
            return ResponseEntity.badRequest()
                .body(Map.of("error", "ids are required"));
        }

        return ResponseEntity.ok(modelService.getModelCapabilities(req.ids()));
    }
}
