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
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.GetModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateModelWeightRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;

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
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> addModel(
            @RequestBody AddModelRequestDTO req) {
        return ResponseEntity.ok(modelService.addModel(req));
    }

    @PostMapping("/update_model_info")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> updateModelInfo(
            @RequestBody UpdateModelRequestDTO req) {
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
}
