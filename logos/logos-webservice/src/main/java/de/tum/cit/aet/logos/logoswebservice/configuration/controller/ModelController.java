package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

import java.util.List;
import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddModelRequest;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateModelRequest;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;

@RestController
@RequestMapping("/logosdb")
public class ModelController {

    private final ModelService modelService;
    private final PriceUpdaterService priceUpdaterService;

    public ModelController(ModelService modelService, PriceUpdaterService priceUpdaterService) {
        this.modelService = modelService;
        this.priceUpdaterService = priceUpdaterService;
    }

    @PostMapping("/get_models")
    public ResponseEntity<?> getModels(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(modelService.getModels(auth));
    }

    @PostMapping("/add_model")
    public ResponseEntity<?> addModel(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody AddModelRequest req) {
        if (!isLogosAdmin(auth)) return forbidden();
        return ResponseEntity.ok(modelService.addModel(req));
    }

    @PostMapping("/update_model_info")
    public ResponseEntity<?> updateModelInfo(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody UpdateModelRequest req) {
        if (!isLogosAdmin(auth)) return forbidden();
        try {
            ResponseEntity<?> response = ResponseEntity.ok(modelService.updateModelInfo(req));
            if (req.name() != null) {
                priceUpdaterService.updatePricesForModelAsync(req.modelId(), req.name());
            }
            return response;
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/delete_model")
    public ResponseEntity<?> deleteModel(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody Map<String, Object> body) {
        if (!isLogosAdmin(auth)) return forbidden();
        Integer id = (Integer) body.get("id");
        if (id == null) return ResponseEntity.badRequest().body(Map.of("error", "id is required"));
        try {
            return ResponseEntity.ok(modelService.deleteModel(id));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/get_model")
    public ResponseEntity<?> getModel(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody Map<String, Object> body) {
        Integer id = (Integer) body.get("id");
        if (id == null) return ResponseEntity.badRequest().body(Map.of("error", "id is required"));
        return modelService.getModel(id)
            .map(ResponseEntity::ok)
            .<ResponseEntity<?>>map(r -> r)
            .orElse(ResponseEntity.status(404).body(Map.of("error", "Model not found")));
    }

    @PostMapping("/get_general_model_stats")
    public ResponseEntity<?> getGeneralModelStats(
            @RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(modelService.getGeneralModelStats());
    }

    @PostMapping("/update_model")
    public ResponseEntity<?> updateModel(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody Map<String, Object> body) {
        if (!isLogosAdmin(auth)) return forbidden();
        Integer id       = body.get("id") instanceof Number n ? n.intValue() : null;
        String  category = (String) body.get("category");
        Integer value    = body.get("value") instanceof Number n ? n.intValue() : null;
        if (id == null || category == null || value == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "id, category, and value are required"));
        }
        try {
            return ResponseEntity.ok(modelService.updateModelWeight(id, category, value));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    private static boolean isLogosAdmin(AuthContext auth) {
        return "logos_admin".equals(auth.role());
    }

    private static ResponseEntity<?> forbidden() {
        return ResponseEntity.status(403).body(Map.of("detail", "Forbidden"));
    }
}
