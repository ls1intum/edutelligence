package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.SetLogRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.service.ApiKeyAdminService;
import de.tum.cit.aet.logos.logoswebservice.identity.service.MeService;

@RestController
public class MeController {

    private final MeService meService;
    private final ApiKeyAdminService apiKeyAdminService;

    public MeController(MeService meService, ApiKeyAdminService apiKeyAdminService) {
        this.meService = meService;
        this.apiKeyAdminService = apiKeyAdminService;
    }

    @PostMapping("/logosdb/get_role")
    public ResponseEntity<?> getRole(@RequestAttribute("authContext") AuthContext auth) {
        String role = "logos_admin".equals(auth.role()) ? "root" : "entity";
        return ResponseEntity.ok(Map.of("role", role));
    }

    @PostMapping("/logosdb/get_api_key_id")
    public ResponseEntity<?> getApiKeyId(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(Map.of("result", auth.apiKeyId()));
    }

    @PostMapping("/logosdb/set_log")
    public ResponseEntity<?> setLog(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody SetLogRequestDTO req) {
        Integer targetId = req.apiKeyId() != null ? req.apiKeyId() : req.processId();
        if (targetId == null || req.setLog() == null) {
            return ResponseEntity.badRequest().body(
                Map.of("error", "api_key_id (or process_id) and set_log are required"));
        }
        if (!targetId.equals(auth.apiKeyId()) && !"logos_admin".equals(auth.role())) {
            return ResponseEntity.status(403).body(Map.of("error", "Missing authentication to set log"));
        }
        return ResponseEntity.ok(apiKeyAdminService.setLog(targetId, req.setLog()));
    }

    @GetMapping("/me")
    public ResponseEntity<?> getMe(@RequestAttribute("authContext") AuthContext auth) {
        if (auth.userId() == null) {
            return ResponseEntity.status(404).body(
                Map.of("detail", "No user linked to this key. Service keys cannot log into the UI.")
            );
        }
        return meService.getMe(auth.userId())
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElseGet(() -> ResponseEntity.status(404).body(
                Map.of("detail", "No user linked to this key. Service keys cannot log into the UI.")
            ));
    }
}
