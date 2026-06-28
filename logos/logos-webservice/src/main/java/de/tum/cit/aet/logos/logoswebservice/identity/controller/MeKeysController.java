package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.ModelAccessDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.service.MeKeysService;

@RestController
@RequestMapping("/me/keys")
public class MeKeysController {

    private final MeKeysService meKeysService;
    private final ApiKeyRepository apiKeyRepository;

    public MeKeysController(MeKeysService meKeysService, ApiKeyRepository apiKeyRepository) {
        this.meKeysService = meKeysService;
        this.apiKeyRepository = apiKeyRepository;
    }

    @GetMapping
    public ResponseEntity<?> getMyKeys(@RequestAttribute("authContext") AuthContext auth) {
        if (auth.userId() == null) {
            return ResponseEntity.status(403).body(Map.of("detail", "Service keys cannot access My Keys."));
        }
        return ResponseEntity.ok(meKeysService.getKeysForUser(auth.userId()));
    }

    @PatchMapping("/{keyId}/log")
    public ResponseEntity<?> setLog(
            @PathVariable Integer keyId,
            @RequestBody Map<String, String> body,
            @RequestAttribute("authContext") AuthContext auth) {
        if (auth.userId() == null) {
            return ResponseEntity.status(403).body(Map.of("detail", "Service keys cannot update log level."));
        }
        String level = body == null ? null : body.get("log");
        if (level == null || (!level.equals("BILLING") && !level.equals("FULL"))) {
            return ResponseEntity.badRequest().body(Map.of("detail", "log must be BILLING or FULL"));
        }
        Optional<ApiKey> keyOpt = apiKeyRepository.findById(keyId);
        if (keyOpt.isEmpty()) {
            return ResponseEntity.status(404).body(Map.of("detail", "API key not found."));
        }
        ApiKey key = keyOpt.get();
        if (!auth.userId().equals(key.getUserId())) {
            return ResponseEntity.status(403).body(Map.of("detail", "You do not own this API key."));
        }
        Optional<Map<String, Object>> result = meKeysService.setLogForUser(keyId, auth.userId(), level);
        return result
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElseGet(() -> ResponseEntity.status(404).body(Map.of("detail", "API key not found or not owned.")));
    }

    @GetMapping("/{keyId}/models")
    public ResponseEntity<?> getAccessibleModels(
            @PathVariable Integer keyId,
            @RequestAttribute("authContext") AuthContext auth) {
        if (auth.userId() == null) {
            return ResponseEntity.status(403).body(Map.of("detail", "Service keys cannot access model list."));
        }
        Optional<ApiKey> keyOpt = apiKeyRepository.findById(keyId);
        if (keyOpt.isEmpty()) {
            return ResponseEntity.status(404).body(Map.of("detail", "API key not found."));
        }
        ApiKey key = keyOpt.get();
        if (!auth.userId().equals(key.getUserId())) {
            return ResponseEntity.status(403).body(Map.of("detail", "You do not own this API key."));
        }
        Optional<List<ModelAccessDTO>> result = meKeysService.getAccessibleModels(keyId, auth.userId());
        return result
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElseGet(() -> ResponseEntity.status(404).body(Map.of("detail", "API key not found or not owned.")));
    }
}
