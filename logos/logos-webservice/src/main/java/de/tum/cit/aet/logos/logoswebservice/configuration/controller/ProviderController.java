package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddProviderRequest;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ConnectModelProviderRequest;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DisconnectModelProviderRequest;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateProviderRequest;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ProviderService;

@RestController
@RequestMapping("/logosdb")
public class ProviderController {

    private final ProviderService providerService;

    public ProviderController(ProviderService providerService) {
        this.providerService = providerService;
    }

    @PostMapping("/get_providers")
    public ResponseEntity<?> getProviders(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(providerService.getProviders(auth));
    }

    @PostMapping("/add_provider")
    public ResponseEntity<?> addProvider(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody AddProviderRequest req) {
        if (!isLogosAdmin(auth)) return forbidden();
        try {
            return ResponseEntity.ok(providerService.addProvider(req));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/update_provider")
    public ResponseEntity<?> updateProvider(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody UpdateProviderRequest req) {
        if (!isLogosAdmin(auth)) return forbidden();
        try {
            return ResponseEntity.ok(providerService.updateProvider(req));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/delete_provider")
    public ResponseEntity<?> deleteProvider(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody Map<String, Object> body) {
        if (!isLogosAdmin(auth)) return forbidden();
        Integer providerId = (Integer) body.get("provider_id");
        if (providerId == null) return ResponseEntity.badRequest().body(Map.of("error", "provider_id is required"));
        try {
            return ResponseEntity.ok(providerService.deleteProvider(providerId));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/connect_model_provider")
    public ResponseEntity<?> connectModelProvider(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody ConnectModelProviderRequest req) {
        if (!isLogosAdmin(auth)) return forbidden();
        return ResponseEntity.ok(providerService.connectModelProvider(req));
    }

    @PostMapping("/disconnect_model_provider")
    public ResponseEntity<?> disconnectModelProvider(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody DisconnectModelProviderRequest req) {
        if (!isLogosAdmin(auth)) return forbidden();
        try {
            return ResponseEntity.ok(providerService.disconnectModelProvider(req));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/get_provider_models")
    public ResponseEntity<?> getProviderModels(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody Map<String, Object> body) {
        Integer providerId = (Integer) body.get("provider_id");
        if (providerId == null) return ResponseEntity.badRequest().body(Map.of("error", "provider_id is required"));
        return ResponseEntity.ok(providerService.getProviderModels(providerId));
    }

    @PostMapping("/get_general_provider_stats")
    public ResponseEntity<?> getGeneralProviderStats(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(providerService.getGeneralProviderStats());
    }

    private static boolean isLogosAdmin(AuthContext auth) {
        return "logos_admin".equals(auth.role());
    }

    private static ResponseEntity<?> forbidden() {
        return ResponseEntity.status(403).body(Map.of("detail", "Forbidden"));
    }
}
