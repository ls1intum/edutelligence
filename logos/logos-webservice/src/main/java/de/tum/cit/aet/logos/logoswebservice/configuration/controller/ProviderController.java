package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

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
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.CalibrateUncalibratedRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ConnectModelProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DeleteLaneRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DeleteProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DisconnectModelProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.GetProviderModelsRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ProviderService;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorWorkerAdminClient;

@RestController
@RequestMapping("/logosdb")
public class ProviderController {

    private final ProviderService providerService;
    private final OrchestratorWorkerAdminClient workerAdminClient;
    private final ObjectMapper objectMapper;

    public ProviderController(ProviderService providerService, OrchestratorWorkerAdminClient workerAdminClient, ObjectMapper objectMapper) {
        this.providerService = providerService;
        this.workerAdminClient = workerAdminClient;
        this.objectMapper = objectMapper;
    }

    @PostMapping("/get_providers")
    public ResponseEntity<?> getProviders(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(providerService.getProviders(auth));
    }

    @PostMapping("/add_provider")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> addProvider(
            @RequestBody AddProviderRequestDTO req) {
        try {
            return ResponseEntity.ok(providerService.addProvider(req));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/update_provider")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> updateProvider(
            @RequestBody UpdateProviderRequestDTO req) {
        try {
            return ResponseEntity.ok(providerService.updateProvider(req));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/delete_provider")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> deleteProvider(
            @RequestBody DeleteProviderRequestDTO req) {
        if (req.providerId() == null) return ResponseEntity.badRequest().body(Map.of("error", "provider_id is required"));
        try {
            return ResponseEntity.ok(providerService.deleteProvider(req.providerId()));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/connect_model_provider")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> connectModelProvider(
            @RequestBody ConnectModelProviderRequestDTO req) {
        return ResponseEntity.ok(providerService.connectModelProvider(req));
    }

    @PostMapping("/disconnect_model_provider")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> disconnectModelProvider(
            @RequestBody DisconnectModelProviderRequestDTO req) {
        try {
            return ResponseEntity.ok(providerService.disconnectModelProvider(req));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(404).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/get_provider_models")
    public ResponseEntity<?> getProviderModels(
            @RequestBody GetProviderModelsRequestDTO req) {
        if (req.providerId() == null) return ResponseEntity.badRequest().body(Map.of("error", "provider_id is required"));
        return ResponseEntity.ok(providerService.getProviderModels(req.providerId()));
    }

    @PostMapping("/get_general_provider_stats")
    public ResponseEntity<?> getGeneralProviderStats() {
        return ResponseEntity.ok(providerService.getGeneralProviderStats());
    }

    @PostMapping("/providers/logosnode/calibrate_uncalibrated")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> calibrateUncalibrated(@RequestBody CalibrateUncalibratedRequestDTO req) {
        if (req.providerId() == null) return ResponseEntity.badRequest().body(Map.of("error", "provider_id is required"));
        try {
            return workerAdminClient.calibrateUncalibrated(req.providerId());
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode()).body(parseOrWrap(e.getResponseBodyAsString()));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/providers/logosnode/lanes/delete")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> deleteLane(@RequestBody DeleteLaneRequestDTO req) {
        if (req.providerId() == null || req.laneId() == null)
            return ResponseEntity.badRequest().body(Map.of("error", "provider_id and lane_id are required"));
        try {
            return workerAdminClient.deleteLane(req.providerId(), req.laneId());
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode()).body(parseOrWrap(e.getResponseBodyAsString()));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(Map.of("error", e.getMessage()));
        }
    }

    private Object parseOrWrap(String body) {
        try {
            return objectMapper.readValue(body, Map.class);
        } catch (Exception e) {
            return Map.of("error", body);
        }
    }
}
