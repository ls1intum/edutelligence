package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClientResponseException;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DeleteModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.GetModelCalibrationLogRequestDTO;
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

import jakarta.servlet.http.HttpServletRequest;

@RestController
@RequestMapping("/logosdb")
public class ModelController {

    private final ModelService modelService;
    private final PriceUpdaterService priceUpdaterService;
    private final ModelCapabilitiesUpdaterService modelCapabilitiesUpdaterService;
    private final OrchestratorCalibrationLogsClient orchestratorCalibrationLogsClient;
    private final ObjectMapper objectMapper;

    public ModelController(ModelService modelService,
                           PriceUpdaterService priceUpdaterService,
                           ModelCapabilitiesUpdaterService modelCapabilitiesUpdaterService,
                           OrchestratorCalibrationLogsClient orchestratorCalibrationLogsClient,
                           ObjectMapper objectMapper) {
        this.modelService = modelService;
        this.priceUpdaterService = priceUpdaterService;
        this.modelCapabilitiesUpdaterService = modelCapabilitiesUpdaterService;
        this.orchestratorCalibrationLogsClient = orchestratorCalibrationLogsClient;
        this.objectMapper = objectMapper;
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
        try {
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
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/update_model_info")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> updateModelInfo(
            @RequestBody UpdateModelRequestDTO req) {
        try {
            Map<String, Object> result = new LinkedHashMap<>(modelService.updateModelInfo(req));
            if (req.name() != null) {
                priceUpdaterService.updatePricesForModelAsync(req.modelId(), req.name());
                // Capabilities resolve against a local catalog file, so this runs
                // inline rather than async: the response then carries the state
                // the rename produced, and the client does not have to keep the
                // flags of the old name on screen until the next full reload.
                modelCapabilitiesUpdaterService.updateCapabilitiesForModel(req.modelId(), req.name());
                result.put("capabilities", modelService.capabilitiesState(req.modelId()));
            }
            return ResponseEntity.ok(result);
        } catch (IllegalArgumentException e) {
            // "Model not found: ..." is a lookup miss; alias validation
            // failures are bad input.
            int status = e.getMessage() != null && e.getMessage().startsWith("Model not found")
                ? 404
                : 400;
            return ResponseEntity.status(status).body(Map.of("error", e.getMessage()));
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

    /**
     * On-demand fetch of one node's full calibration log straight from the
     * worker. Backs the Complete-Logs tab's Download-full-logs button for
     * successful calibrations, whose log is no longer stored in the DB.
     */
    @PostMapping("/get_model_calibration_log_full")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> getModelCalibrationLogFull(
            @RequestBody GetModelCalibrationLogRequestDTO req) {
        if (req.id() == null || req.providerId() == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "id and provider_id are required"));
        }
        return modelService.getModel(req.id())
            .<ResponseEntity<?>>map(model -> {
                try {
                    return orchestratorCalibrationLogsClient.fetchFullLog(req.providerId(), (String) model.get("name"));
                } catch (RestClientResponseException e) {
                    return ResponseEntity.status(e.getStatusCode()).body(parseOrWrap(e.getResponseBodyAsString()));
                } catch (Exception e) {
                    return ResponseEntity.status(503).body(Map.of("error", errorMessage(e)));
                }
            })
            .orElse(ResponseEntity.status(404).body(Map.of("error", "Model not found")));
    }

    /** Map.of rejects null values; some exceptions have a null message. */
    private String errorMessage(Exception e) {
        return e.getMessage() != null ? e.getMessage() : e.toString();
    }

    private Object parseOrWrap(String body) {
        try {
            return objectMapper.readValue(body, Map.class);
        } catch (Exception e) {
            return Map.of("error", body);
        }
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
        // A null element is malformed input, not a lookup miss: without this the
        // service's "Model not found: null" would surface as a 404.
        if (req.ids().contains(null)) {
            return ResponseEntity.badRequest()
                .body(Map.of("error", "ids must not contain null"));
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
