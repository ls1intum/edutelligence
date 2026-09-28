package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

import java.util.List;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.RemoveModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.RequestedModelResponse;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.SubmitModelRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.RequestedModelService;

/**
 * The model-request voting page (embedded in the Models view): vote for a model
 * Logos does not serve yet, take the vote back, and see what everyone has voted
 * for.
 *
 * This is a demand signal, not a configuration change — nothing here provisions
 * a model. It is open to every authenticated role (like the model list), since
 * anyone with an account may want a model that is not on the platform yet. The
 * voter is the authenticated user, so "one vote per user per model" and undo
 * are keyed to them.
 */
@RestController
@RequestMapping("/logosdb")
public class ModelRequestController {

    private final RequestedModelService requestedModelService;

    public ModelRequestController(RequestedModelService requestedModelService) {
        this.requestedModelService = requestedModelService;
    }

    /** The requested models, most-voted first, with the caller's vote state. */
    @PostMapping("/get_model_requests")
    public ResponseEntity<List<RequestedModelResponse>> getModelRequests(
            @RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(requestedModelService.list(auth.userId()));
    }

    /**
     * Cast the caller's vote for a model. Refused (409) when the model is
     * already served by Logos. Re-voting an already-voted model is a no-op.
     */
    @PostMapping("/add_model_request")
    public ResponseEntity<?> addModelRequest(@RequestBody SubmitModelRequestDTO req,
                                             @RequestAttribute("authContext") AuthContext auth) {
        if (req == null || req.name() == null || req.name().isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "name is required"));
        }
        try {
            return ResponseEntity.ok(requestedModelService.vote(auth.userId(), req.name()));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        } catch (RequestedModelService.ModelAlreadyAvailableException e) {
            return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("error", e.getMessage()));
        }
    }

    /** Take the caller's vote back for a model. Idempotent. */
    @PostMapping("/remove_model_request")
    public ResponseEntity<?> removeModelRequest(@RequestBody RemoveModelRequestDTO req,
                                                @RequestAttribute("authContext") AuthContext auth) {
        if (req == null || req.name() == null || req.name().isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "name is required"));
        }
        try {
            return ResponseEntity.ok(requestedModelService.undo(auth.userId(), req.name()));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }
}
