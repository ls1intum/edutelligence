package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import jakarta.servlet.http.HttpServletRequest;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.PasskeyDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.service.PasskeyService;

/**
 * Management of the current user's passkeys (#694): list, add multiple,
 * delete. Follows the /me/keys conventions — service keys (no linked user)
 * are rejected, foreign resources 404/403 like everywhere else.
 */
@RestController
@RequestMapping("/me/passkeys")
public class MePasskeysController {

    private final PasskeyService passkeyService;

    public MePasskeysController(PasskeyService passkeyService) {
        this.passkeyService = passkeyService;
    }

    @GetMapping
    public ResponseEntity<?> getMyPasskeys(@RequestAttribute("authContext") AuthContext auth) {
        if (auth.userId() == null) {
            return ResponseEntity.status(403).body(Map.of("detail", "Service keys cannot access passkeys."));
        }
        return ResponseEntity.ok(passkeyService.listForUser(auth.userId()));
    }

    @PostMapping("/options")
    public ResponseEntity<?> registrationOptions(
            @RequestAttribute("authContext") AuthContext auth,
            HttpServletRequest request) {
        if (auth.userId() == null) {
            return ResponseEntity.status(403).body(Map.of("detail", "Service keys cannot register passkeys."));
        }
        return ResponseEntity.ok(passkeyService.registrationOptions(auth.userId(), request));
    }

    @PostMapping
    public ResponseEntity<?> register(
            @RequestBody Map<String, String> body,
            @RequestAttribute("authContext") AuthContext auth,
            HttpServletRequest request) {
        if (auth.userId() == null) {
            return ResponseEntity.status(403).body(Map.of("detail", "Service keys cannot register passkeys."));
        }
        if (body == null
                || body.get("credentialId") == null
                || body.get("clientDataJSON") == null
                || body.get("attestationObject") == null
                || body.get("challenge") == null) {
            return ResponseEntity.badRequest().body(Map.of(
                "detail", "credentialId, clientDataJSON, attestationObject and challenge are required"));
        }
        PasskeyDTO passkey = passkeyService.register(
            auth.userId(),
            body.get("credentialId"),
            body.get("clientDataJSON"),
            body.get("attestationObject"),
            body.get("challenge"),
            body.get("label"),
            request);
        return ResponseEntity.ok(Map.of("result", "Passkey added", "passkey", passkey));
    }

    @DeleteMapping("/{passkeyId}")
    public ResponseEntity<?> delete(
            @PathVariable Integer passkeyId,
            @RequestAttribute("authContext") AuthContext auth) {
        if (auth.userId() == null) {
            return ResponseEntity.status(403).body(Map.of("detail", "Service keys cannot delete passkeys."));
        }
        passkeyService.delete(passkeyId, auth.userId());
        return ResponseEntity.ok(Map.of("result", "Passkey deleted"));
    }
}
