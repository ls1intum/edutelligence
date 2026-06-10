package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.identity.service.ApiKeyAdminService;
import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateUserRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateUserInfoRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateUserRoleRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.identity.service.UserService;

@RestController
@RequestMapping("/users")
public class UserController {

    private final UserService userService;
    private final ApiKeyAdminService apiKeyAdminService;

    public UserController(UserService userService, ApiKeyAdminService apiKeyAdminService) {
        this.userService = userService;
        this.apiKeyAdminService = apiKeyAdminService;
    }

    @GetMapping
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> listUsers(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(userService.listUsers());
    }

    @GetMapping("/admins")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> listAdmins(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(userService.listAdmins());
    }

    @PostMapping
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> createUser(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody CreateUserRequestDTO body) {
        List<String> validRoles = List.of("app_developer", "app_admin", "logos_admin");
        if (!validRoles.contains(body.role())) {
            return ResponseEntity.status(422).body(Map.of("detail", "Invalid role"));
        }
        if ("app_admin".equals(auth.role()) && !"app_developer".equals(body.role())) {
            return ResponseEntity.status(403).body(Map.of("detail", "App admins can only create app_developer users"));
        }
        if ("app_admin".equals(auth.role()) && body.team_ids() != null && auth.userId() != null) {
            for (Integer teamId : body.team_ids()) {
                if (!apiKeyAdminService.isTeamOwner(teamId, auth.userId())) {
                    return ResponseEntity.status(403).body(Map.of("detail", "App admins can only add users to teams they own"));
                }
            }
        }
        try {
            return ResponseEntity.ok(userService.createUser(body));
        } catch (UserService.DuplicateEmailException e) {
            return ResponseEntity.status(409).body(Map.of("detail", e.getMessage()));
        }
    }

    @DeleteMapping("/{userId}")
    @PreAuthorize("hasAuthority('logos_admin')")
    public ResponseEntity<?> deleteUser(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer userId) {
        if (!userService.deleteUser(userId)) {
            return ResponseEntity.status(404).body(Map.of("detail", "User not found"));
        }
        return ResponseEntity.ok(Map.of("message", "User deleted"));
    }

    @PatchMapping("/{userId}/role")
    @PreAuthorize("hasAuthority('logos_admin')")
    public ResponseEntity<?> patchUserRole(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer userId,
            @RequestBody UpdateUserRoleRequestDTO body) {
        return userService.updateRole(userId, body.role())
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElse(ResponseEntity.status(404).body(null));
    }

    @PatchMapping("/{userId}")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> patchUserInfo(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer userId,
            @RequestBody UpdateUserInfoRequestDTO body) {
        if ("app_admin".equals(auth.role()) && !userId.equals(auth.userId())) {
            Optional<String> targetRole = userService.findRole(userId);
            if (targetRole.isEmpty()) {
                return ResponseEntity.status(404).body(null);
            }
            if ("app_admin".equals(targetRole.get()) || "logos_admin".equals(targetRole.get())) {
                return ResponseEntity.status(403).body(Map.of("detail", "App admins cannot edit other administrators"));
            }
        }
        return userService.updateInfo(userId, body)
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElse(ResponseEntity.status(404).body(null));
    }

    @PostMapping("/import")
    @PreAuthorize("hasAnyAuthority('logos_admin', 'app_admin')")
    public ResponseEntity<?> importUsers(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestParam("file") org.springframework.web.multipart.MultipartFile file) {
        if (!file.getOriginalFilename().endsWith(".csv")) {
            return ResponseEntity.status(400).body(Map.of("detail", "Only .csv files are accepted."));
        }
        try {
            return ResponseEntity.ok(userService.importUsers(file));
        } catch (Exception e) {
            return ResponseEntity.status(400).body(Map.of("error", e.getMessage()));
        }
    }

    public static boolean isAppAdminOrAbove(AuthContext auth) {
        return "app_admin".equals(auth.role()) || "logos_admin".equals(auth.role());
    }

    public static boolean isLogosAdmin(AuthContext auth) {
        return "logos_admin".equals(auth.role());
    }

    public static ResponseEntity<Map<String, String>> forbidden() {
        return ResponseEntity.status(403).body(Map.of("detail", "Insufficient permissions"));
    }
}
