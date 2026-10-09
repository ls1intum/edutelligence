package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;

import com.fasterxml.jackson.annotation.JsonProperty;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.identity.service.SessionApiKeyService;

/**
 * Internal mint/revoke of short-lived session API keys for the agent runner.
 *
 * <p>Authenticated with {@code LOGOS_INTERNAL_SECRET}, not a JWT or Logos key.
 */
@RestController
@RequestMapping("/internal/session_api_keys")
public class InternalSessionApiKeyController {

    private final SessionApiKeyService sessionApiKeyService;
    private final String internalSecret;

    public InternalSessionApiKeyController(
            SessionApiKeyService sessionApiKeyService,
            @Value("${logos.orchestrator.internal-secret:}") String internalSecret) {
        this.sessionApiKeyService = sessionApiKeyService;
        this.internalSecret = internalSecret;
    }

    @PostMapping
    public ResponseEntity<?> mint(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody MintRequest request) {
        if (!authorized(authorization)) {
            return ResponseEntity.status(401).body(Map.of("error", "unauthorized"));
        }
        try {
            int ttl = request.ttlSeconds() == null ? 0 : request.ttlSeconds();
            return ResponseEntity.ok(sessionApiKeyService.mint(
                request.parentKeyValue(), ttl, request.name()));
        } catch (IllegalArgumentException exc) {
            return ResponseEntity.badRequest().body(Map.of("error", exc.getMessage()));
        }
    }

    @PostMapping("/{id}/revoke")
    public ResponseEntity<?> revoke(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @PathVariable("id") int id) {
        if (!authorized(authorization)) {
            return ResponseEntity.status(401).body(Map.of("error", "unauthorized"));
        }
        try {
            sessionApiKeyService.revoke(id);
            return ResponseEntity.ok(Map.of("status", "revoked", "id", id));
        } catch (IllegalArgumentException exc) {
            return ResponseEntity.status(404).body(Map.of("error", exc.getMessage()));
        }
    }

    private boolean authorized(String authorization) {
        if (internalSecret.isBlank() || authorization == null || !authorization.startsWith("Bearer ")) {
            return false;
        }
        return MessageDigest.isEqual(
            internalSecret.getBytes(StandardCharsets.UTF_8),
            authorization.substring("Bearer ".length()).getBytes(StandardCharsets.UTF_8));
    }

    public record MintRequest(
            @JsonProperty("parent_key_value") String parentKeyValue,
            @JsonProperty("ttl_seconds") Integer ttlSeconds,
            @JsonProperty("name") String name) {}
}
