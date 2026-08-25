package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

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
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.GetModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ResetModelCapabilitiesRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.SetModelCapabilitiesRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateModelWeightRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelCapabilitiesUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorCalibrationLogsClient;

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

        try {
            return ResponseEntity.ok(modelService.getModelCapabilities(req.ids()));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/set_model_capabilities")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> setModelCapabilities(
            @RequestBody SetModelCapabilitiesRequestDTO req) {
        if (req.modelId() == null
                || req.supportsFunctionCalling() == null
                || req.supportsVision() == null
                || req.supportsReasoning() == null) {
            return ResponseEntity.badRequest().body(Map.of(
                "error", "model_id, supports_function_calling, supports_vision, and supports_reasoning are required"));
        }
        try {
            return ResponseEntity.ok(modelService.setModelCapabilities(
                req.modelId(),
                req.supportsFunctionCalling(),
                req.supportsVision(),
                req.supportsReasoning()
            ));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/reset_model_capabilities")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> resetModelCapabilities(
            @RequestBody ResetModelCapabilitiesRequestDTO req) {
        if (req.modelId() == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "model_id is required"));
        }
        try {
            return ResponseEntity.ok(modelService.resetModelCapabilities(req.modelId()));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }
}
