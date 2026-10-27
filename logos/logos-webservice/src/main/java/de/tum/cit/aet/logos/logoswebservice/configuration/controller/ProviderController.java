package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

import java.util.HashMap;
import java.util.Map;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClientResponseException;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.audit.AuditLogService;
import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddLaneRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.CalibrateUncalibratedRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ConnectModelProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DeleteLaneRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DeleteProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DisconnectModelProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DrainLaneRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.LaneLoadStatusRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.LockLaneRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ReleaseCalibrationClaimRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ReleaseRecoveryRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UnlockLaneRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.LaneLockService;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.GetProviderModelsRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.SleepLaneRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.StopCalibrationRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.WakeLaneRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PriceUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ModelCapabilitiesUpdaterService;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.ProviderService;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorModelSyncClient;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorWorkerAdminClient;

@RestController
@RequestMapping("/logosdb")
public class ProviderController {

    private final ProviderService providerService;
    private final PriceUpdaterService priceUpdaterService;
    private final ModelCapabilitiesUpdaterService modelCapabilitiesUpdaterService;
    private final ModelRepository modelRepository;
    private final OrchestratorWorkerAdminClient workerAdminClient;
    private final OrchestratorModelSyncClient modelSyncClient;
    private final ObjectMapper objectMapper;
    private final LaneLockService laneLockService;
    private final AuditLogService auditLog;

    public ProviderController(ProviderService providerService, PriceUpdaterService priceUpdaterService, ModelCapabilitiesUpdaterService modelCapabilitiesUpdaterService, ModelRepository modelRepository, OrchestratorWorkerAdminClient workerAdminClient, OrchestratorModelSyncClient modelSyncClient, ObjectMapper objectMapper, LaneLockService laneLockService, AuditLogService auditLog) {
        this.laneLockService = laneLockService;
        this.auditLog = auditLog;
        this.providerService = providerService;
        this.priceUpdaterService = priceUpdaterService;
        this.modelCapabilitiesUpdaterService = modelCapabilitiesUpdaterService;
        this.modelRepository = modelRepository;
        this.workerAdminClient = workerAdminClient;
        this.modelSyncClient = modelSyncClient;
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
        ResponseEntity<?> response = ResponseEntity.ok(providerService.connectModelProvider(req));
        // A model only becomes priceable once it is linked to a cloud provider:
        // before the link, updatePricesForModelAsync finds no cloud pair and
        // skips. Without this trigger prices stayed absent until the next daily
        // refresh, so freshly connected cloud models reported a cost of zero.
        if (req.modelId() != null) {
            priceUpdaterService.updatePricesForModelAsync(req.modelId());
            modelRepository.findById(req.modelId()).ifPresent(model ->
                modelCapabilitiesUpdaterService.updateCapabilitiesForModelAsync(req.modelId(), model.getName()));
        }
        return response;
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

    @PostMapping("/refresh_models")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> refreshModels() {
        try {
            return ResponseEntity.ok(providerService.refreshModels());
        } catch (IllegalStateException e) {
            // The sync was never handed to the orchestrator — reporting 200
            // would leave the UI polling a status that can never arrive.
            return ResponseEntity.status(503).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/model_sync_status")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> modelSyncStatus() {
        // null means "could not be read" and keeps the UI polling; Map.of
        // rejects null values.
        Map<String, Object> body = new HashMap<>();
        body.put("running", modelSyncClient.isSyncRunning());
        return ResponseEntity.ok(body);
    }

    @PostMapping("/get_provider_models")
    public ResponseEntity<?> getProviderModels(
            @RequestBody GetProviderModelsRequestDTO req,
            @RequestAttribute("authContext") AuthContext auth) {
        if (req.providerId() == null) return ResponseEntity.badRequest().body(Map.of("error", "provider_id is required"));
        return ResponseEntity.ok(providerService.getProviderModels(req.providerId(), auth));
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

    @PostMapping("/providers/logosnode/stop_calibration")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> stopCalibration(@RequestBody StopCalibrationRequestDTO req) {
        if (req.providerId() == null) return ResponseEntity.badRequest().body(Map.of("error", "provider_id is required"));
        try {
            return workerAdminClient.stopCalibration(req.providerId());
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode()).body(parseOrWrap(e.getResponseBodyAsString()));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(errorBody(e));
        }
    }

    /**
     * What holds the maintenance slot: calibrations, benchmarks and nightly recoveries.
     * Keep the public maintenance paths outside /providers/logosnode, whose proxy
     * catch-all routes to the orchestrator rather than this webservice.
     */
    @GetMapping({"/maintenance", "/providers/logosnode/maintenance"})
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> maintenanceStatus() {
        try {
            return workerAdminClient.maintenanceStatus();
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode()).body(parseOrWrap(e.getResponseBodyAsString()));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(errorBody(e));
        }
    }

    /**
     * Releases a calibration claim that a normal stop could not release, for
     * example because the worker is offline. Recorded in the audit trail.
     */
    @PostMapping({"/maintenance/release_calibration", "/providers/logosnode/maintenance/release_calibration"})
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> releaseCalibrationClaim(@RequestBody ReleaseCalibrationClaimRequestDTO req) {
        if (req == null || req.providerId() == null || req.claimToken() == null || req.claimToken().isBlank())
            return ResponseEntity.badRequest().body(Map.of("error", "provider_id and claim_token are required"));
        ResponseEntity<Map> response;
        try {
            response = workerAdminClient.releaseCalibrationClaim(req.providerId(), req.claimToken());
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode()).body(parseOrWrap(e.getResponseBodyAsString()));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(errorBody(e));
        }
        Map<?, ?> body = response.getBody();
        if (response.getStatusCode().is2xxSuccessful() && body != null && Boolean.TRUE.equals(body.get("released"))) {
            Map<String, Object> after = new HashMap<>();
            after.put("calibration_claim", null);
            after.put("confirmed_by_worker", !Boolean.TRUE.equals(body.get("forced")));
            auditLog.record("provider.calibration_claim_released", "provider", req.providerId(), null,
                Map.of("calibration_claim", req.claimToken()), after);
        }
        return response;
    }

    /**
     * Releases a nightly recovery that cannot finish on its own. Without force
     * the worker must run the lane's original settings. Recorded in the audit trail.
     */
    @PostMapping({"/maintenance/release_recovery", "/providers/logosnode/maintenance/release_recovery"})
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> releaseRecovery(@RequestBody ReleaseRecoveryRequestDTO req) {
        if (req == null || req.modelProviderId() == null)
            return ResponseEntity.badRequest().body(Map.of("error", "model_provider_id is required"));
        boolean force = Boolean.TRUE.equals(req.force());
        ResponseEntity<Map> response;
        try {
            response = workerAdminClient.releaseRecovery(req.modelProviderId(), force);
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode()).body(parseOrWrap(e.getResponseBodyAsString()));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(errorBody(e));
        }
        Map<?, ?> body = response.getBody();
        if (response.getStatusCode().is2xxSuccessful() && body != null && Boolean.TRUE.equals(body.get("released"))) {
            Map<String, Object> after = new HashMap<>();
            after.put("nightly_recovery", null);
            after.put("forced", Boolean.TRUE.equals(body.get("forced")));
            auditLog.record("provider.nightly_recovery_released", "model_provider", req.modelProviderId(), null,
                Map.of("nightly_recovery", "pending"), after);
        }
        return response;
    }

    @PostMapping("/providers/logosnode/lanes/add")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> addLane(@RequestBody AddLaneRequestDTO req) {
        if (req.providerId() == null || req.lane() == null || req.lane().isEmpty())
            return ResponseEntity.badRequest().body(Map.of("error", "provider_id and lane are required"));
        try {
            return workerAdminClient.addLane(req.providerId(), req.lane());
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode()).body(parseOrWrap(e.getResponseBodyAsString()));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/providers/logosnode/lanes/load_status")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> laneLoadStatus(@RequestBody LaneLoadStatusRequestDTO req) {
        if (req.providerId() == null || req.model() == null || req.model().isBlank())
            return ResponseEntity.badRequest().body(Map.of("error", "provider_id and model are required"));
        try {
            return workerAdminClient.getLaneLoadStatus(req.providerId(), req.model());
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode()).body(parseOrWrap(e.getResponseBodyAsString()));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(errorBody(e));
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

    @PostMapping("/providers/logosnode/lanes/sleep")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> sleepLane(@RequestBody SleepLaneRequestDTO req) {
        if (req.providerId() == null || req.laneId() == null)
            return ResponseEntity.badRequest().body(Map.of("error", "provider_id and lane_id are required"));
        try {
            return workerAdminClient.sleepLane(req.providerId(), req.laneId());
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode()).body(parseOrWrap(e.getResponseBodyAsString()));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(errorBody(e));
        }
    }

    @PostMapping("/providers/logosnode/lanes/drain")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> drainLane(@RequestBody DrainLaneRequestDTO req) {
        if (req.providerId() == null || req.laneId() == null)
            return ResponseEntity.badRequest().body(Map.of("error", "provider_id and lane_id are required"));
        try {
            return workerAdminClient.drainLane(req.providerId(), req.laneId());
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode()).body(parseOrWrap(e.getResponseBodyAsString()));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(errorBody(e));
        }
    }

    @PostMapping("/providers/logosnode/lanes/wake")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> wakeLane(@RequestBody WakeLaneRequestDTO req) {
        if (req.providerId() == null || req.laneId() == null)
            return ResponseEntity.badRequest().body(Map.of("error", "provider_id and lane_id are required"));
        try {
            return workerAdminClient.wakeLane(req.providerId(), req.laneId());
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode()).body(parseOrWrap(e.getResponseBodyAsString()));
        } catch (Exception e) {
            return ResponseEntity.status(503).body(errorBody(e));
        }
    }

    /**
     * Lanes locked warm. The capacity planner reads the same table every
     * cycle and never sleeps, drains or unloads a locked lane. A lock with
     * lane id {@code *} locks the whole worker (see {@link LaneLockService}).
     */
    @GetMapping("/providers/logosnode/lanes/locks")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> getLaneLocks() {
        return ResponseEntity.ok(laneLockService.listLocks());
    }

    /** Locks a lane warm. Idempotent: locking a locked lane keeps the existing lock. */
    @PostMapping("/providers/logosnode/lanes/lock")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> lockLane(@RequestAttribute("authContext") AuthContext auth,
                                      @RequestBody LockLaneRequestDTO req) {
        if (req == null || req.providerId() == null || req.laneId() == null || req.laneId().isBlank())
            return ResponseEntity.badRequest().body(Map.of("error", "provider_id and lane_id are required"));
        try {
            return ResponseEntity.ok(laneLockService.lock(auth, req.providerId(), req.laneId().trim(), req.modelName()));
        } catch (DataIntegrityViolationException e) {
            return ResponseEntity.status(404).body(Map.of("error", "Unknown provider " + req.providerId()));
        }
    }

    /** Releases a lane lock. Idempotent: unlocking an unlocked lane succeeds. */
    @PostMapping("/providers/logosnode/lanes/unlock")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> unlockLane(@RequestBody UnlockLaneRequestDTO req) {
        if (req == null || req.providerId() == null || req.laneId() == null || req.laneId().isBlank())
            return ResponseEntity.badRequest().body(Map.of("error", "provider_id and lane_id are required"));
        boolean removed = laneLockService.unlock(req.providerId(), req.laneId().trim());
        return ResponseEntity.ok(Map.of("unlocked", removed));
    }

    /** e.getMessage() is null for some exceptions, and Map.of rejects null values. */
    private Object errorBody(Exception e) {
        return Map.of("error", e.getMessage() != null ? e.getMessage() : e.toString());
    }

    private Object parseOrWrap(String body) {
        try {
            return objectMapper.readValue(body, Map.class);
        } catch (Exception e) {
            return Map.of("error", body);
        }
    }
}
