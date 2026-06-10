package de.tum.cit.aet.logos.logoswebservice.configuration.controller;

import java.util.Map;
import java.util.Optional;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.SetModelPermissionsRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.SetProviderPermissionsRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.service.PermissionService;
import de.tum.cit.aet.logos.logoswebservice.identity.service.ApiKeyAdminService;

import static de.tum.cit.aet.logos.logoswebservice.identity.controller.UserController.isLogosAdmin;

@RestController
@RequestMapping("/admin")
public class PermissionController {

    private final PermissionService permissionService;
    private final ApiKeyAdminService apiKeyService;

    public PermissionController(PermissionService permissionService, ApiKeyAdminService apiKeyService) {
        this.permissionService = permissionService;
        this.apiKeyService = apiKeyService;
    }

    @GetMapping("/api-keys/{keyId}/model-permissions")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> getApiKeyModelPermissions(
            @PathVariable Integer keyId,
            @RequestAttribute("authContext") AuthContext auth) {
        ResponseEntity<?> deny = enforceKeyAccess(keyId, auth);
        if (deny != null) return deny;
        return ResponseEntity.ok(permissionService.getApiKeyModelPermissions(keyId));
    }

    @PutMapping("/api-keys/{keyId}/model-permissions")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> setApiKeyModelPermissions(
            @PathVariable Integer keyId,
            @RequestBody SetModelPermissionsRequestDTO body,
            @RequestAttribute("authContext") AuthContext auth) {
        ResponseEntity<?> deny = enforceKeyAccess(keyId, auth);
        if (deny != null) return deny;
        permissionService.setApiKeyModelPermissions(keyId, body.modelIds());
        return ResponseEntity.ok(Map.of("result", "API Key model permissions updated"));
    }

    @GetMapping("/api-keys/{keyId}/provider-permissions")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> getApiKeyProviderPermissions(
            @PathVariable Integer keyId,
            @RequestAttribute("authContext") AuthContext auth) {
        ResponseEntity<?> deny = enforceKeyAccess(keyId, auth);
        if (deny != null) return deny;
        return ResponseEntity.ok(permissionService.getApiKeyProviderPermissions(keyId));
    }

    @PutMapping("/api-keys/{keyId}/provider-permissions")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> setApiKeyProviderPermissions(
            @PathVariable Integer keyId,
            @RequestBody SetProviderPermissionsRequestDTO body,
            @RequestAttribute("authContext") AuthContext auth) {
        ResponseEntity<?> deny = enforceKeyAccess(keyId, auth);
        if (deny != null) return deny;
        permissionService.setApiKeyProviderPermissions(keyId, body.providerIds());
        return ResponseEntity.ok(Map.of("result", "API Key provider permissions updated"));
    }

    @GetMapping("/teams/{teamId}/model-permissions")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> getTeamModelPermissions(
            @PathVariable Integer teamId) {
        return ResponseEntity.ok(permissionService.getTeamModelPermissions(teamId));
    }

    @PutMapping("/teams/{teamId}/model-permissions")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> setTeamModelPermissions(
            @PathVariable Integer teamId,
            @RequestBody SetModelPermissionsRequestDTO body,
            @RequestAttribute("authContext") AuthContext auth) {
        boolean allowed = isLogosAdmin(auth)
            || ("app_admin".equals(auth.role()) && auth.userId() != null
                && apiKeyService.isTeamOwner(teamId, auth.userId()));
        if (!allowed) return ResponseEntity.status(403).body(Map.of("detail", "Logos Admin or team owner access required"));
        permissionService.setTeamModelPermissions(teamId, body.modelIds());
        return ResponseEntity.ok(Map.of("result", "Team model permissions updated"));
    }

    @GetMapping("/teams/{teamId}/provider-permissions")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> getTeamProviderPermissions(
            @PathVariable Integer teamId) {
        return ResponseEntity.ok(permissionService.getTeamProviderPermissions(teamId));
    }

    @PutMapping("/teams/{teamId}/provider-permissions")
    @PreAuthorize("hasAuthority('logos_admin')")
    public ResponseEntity<?> setTeamProviderPermissions(
            @PathVariable Integer teamId,
            @RequestBody SetProviderPermissionsRequestDTO body) {
        permissionService.setTeamProviderPermissions(teamId, body.providerIds());
        return ResponseEntity.ok(Map.of("result", "Team provider permissions updated"));
    }

    private ResponseEntity<?> enforceKeyAccess(Integer keyId, AuthContext auth) {
        Optional<Map<String, Object>> keyInfo = apiKeyService.getKeyById(keyId);
        if (keyInfo.isEmpty()) return ResponseEntity.status(404).body(Map.of("detail", "API Key not found"));
        if ("app_admin".equals(auth.role())) {
            Integer teamId = (Integer) keyInfo.get().get("team_id");
            if (teamId == null || auth.userId() == null || !apiKeyService.isTeamOwner(teamId, auth.userId())) {
                return ResponseEntity.status(403).body(Map.of("detail", "Team owner access required"));
            }
        }
        return null;
    }
}
