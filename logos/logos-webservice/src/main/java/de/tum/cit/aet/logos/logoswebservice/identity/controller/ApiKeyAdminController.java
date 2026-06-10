package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateAppKeyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateApiKeyRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.service.ApiKeyAdminService;
import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.Optional;

@RestController
@RequestMapping("/admin")
public class ApiKeyAdminController {

    private final ApiKeyAdminService service;

    public ApiKeyAdminController(ApiKeyAdminService service) {
        this.service = service;
    }

    @PostMapping("/teams/{teamId}/api-keys")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> createAppKey(
            @PathVariable Integer teamId,
            @RequestBody CreateAppKeyRequestDTO body,
            @RequestAttribute("authContext") AuthContext auth) {
        if ("app_admin".equals(auth.role()) && !service.isTeamOwner(teamId, auth.userId())) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        String env = body.environment() != null ? body.environment() : "-";
        if (service.duplicateAppKeyExists(teamId, env)) {
            return ResponseEntity.status(400).body(Map.of("detail",
                "An active application key for environment '" + env + "' already exists in this team."));
        }
        return ResponseEntity.ok(service.createAppKey(teamId, body));
    }

    @DeleteMapping("/api-keys/{keyId}")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> deactivateKey(
            @PathVariable Integer keyId,
            @RequestAttribute("authContext") AuthContext auth) {
        Optional<Map<String, Object>> keyInfo = service.getKeyById(keyId);
        if (keyInfo.isEmpty()) return ResponseEntity.status(404).body(Map.of("detail", "API Key not found"));
        if ("app_admin".equals(auth.role())) {
            Integer teamId = (Integer) keyInfo.get().get("team_id");
            if (teamId == null || !service.isTeamOwner(teamId, auth.userId())) {
                return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required to delete this key"));
            }
        }
        service.deactivateKey(keyId);
        return ResponseEntity.ok(Map.of("result", "API Key deleted successfully"));
    }

    @PatchMapping("/api-keys/{keyId}")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> updateKey(
            @PathVariable Integer keyId,
            @RequestBody UpdateApiKeyRequestDTO body,
            @RequestAttribute("authContext") AuthContext auth) {
        Optional<Map<String, Object>> keyInfo = service.getKeyById(keyId);
        if (keyInfo.isEmpty()) return ResponseEntity.status(404).body(Map.of("detail", "API Key not found"));
        if ("app_admin".equals(auth.role())) {
            Integer teamId = (Integer) keyInfo.get().get("team_id");
            if (teamId == null || !service.isTeamOwner(teamId, auth.userId())) {
                return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
            }
        }
        return ResponseEntity.ok(service.updateKey(keyId, body));
    }

    @GetMapping("/teams/{teamId}/api-keys")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> getTeamApiKeys(
            @PathVariable Integer teamId,
            @RequestAttribute("authContext") AuthContext auth) {
        if ("app_admin".equals(auth.role()) && !service.isTeamOwner(teamId, auth.userId())) {
            return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
        }
        return ResponseEntity.ok(service.getKeysForTeam(teamId));
    }
}
