package de.tum.cit.aet.logos.logoswebservice.notifications.controller;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.notifications.dto.PublishNotificationRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.notifications.service.NotificationService;

/**
 * Emission endpoint called by the orchestrator, gated on the internal secret
 * exactly like {@code /internal/models_discovered} (a shared secret, not a
 * JWT, so the resource-server chain must not run for this path — see
 * SecurityConfig). The source is forced to {@code orchestrator}: whatever the
 * caller claims, this endpoint is the orchestrator's door.
 */
@RestController
@RequestMapping("/internal")
public class InternalNotificationController {

    private final NotificationService service;
    private final String internalSecret;

    public InternalNotificationController(
            NotificationService service,
            @Value("${logos.orchestrator.internal-secret:}") String internalSecret) {
        this.service = service;
        this.internalSecret = internalSecret;
    }

    @PostMapping("/notifications")
    public ResponseEntity<?> publish(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody PublishNotificationRequestDTO request) {
        if (!authorized(authorization)) {
            return ResponseEntity.status(401).body(Map.of("error", "unauthorized"));
        }
        PublishNotificationRequestDTO fromOrchestrator = new PublishNotificationRequestDTO(
            request.type(),
            request.title(),
            request.body(),
            request.payload(),
            "orchestrator",
            request.actorUserId(),
            request.targets());
        try {
            long id = service.publish(fromOrchestrator);
            return ResponseEntity.ok(Map.of("status", "accepted", "id", id));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    private boolean authorized(String authorization) {
        return !internalSecret.isBlank()
            && authorization != null
            && authorization.startsWith("Bearer ")
            && MessageDigest.isEqual(
                internalSecret.getBytes(StandardCharsets.UTF_8),
                authorization.substring("Bearer ".length()).getBytes(StandardCharsets.UTF_8));
    }
}
