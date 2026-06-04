package de.tum.cit.aet.logos.logoswebservice.identity.controller;

import java.util.List;
import java.util.Map;

import org.springframework.http.ResponseEntity;
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

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.CreateUserRequest;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateUserInfoRequest;
import de.tum.cit.aet.logos.logoswebservice.identity.dto.UpdateUserRoleRequest;
import de.tum.cit.aet.logos.logoswebservice.identity.service.UserService;

@RestController
@RequestMapping("/users")
public class UserController {

    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    @GetMapping
    public ResponseEntity<?> listUsers(@RequestAttribute("authContext") AuthContext auth) {
        if (!isAppAdminOrAbove(auth)) return forbidden();
        return ResponseEntity.ok(userService.listUsers());
    }

    @GetMapping("/admins")
    public ResponseEntity<?> listAdmins(@RequestAttribute("authContext") AuthContext auth) {
        if (!isAppAdminOrAbove(auth)) return forbidden();
        return ResponseEntity.ok(userService.listAdmins());
    }

    @PostMapping
    public ResponseEntity<?> createUser(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody CreateUserRequest body) {
        if (!isAppAdminOrAbove(auth)) return forbidden();
        List<String> validRoles = List.of("app_developer", "app_admin", "logos_admin");
        if (!validRoles.contains(body.role())) {
            return ResponseEntity.status(422).body(Map.of("detail", "Invalid role"));
        }
        if ("app_admin".equals(auth.role()) && !"app_developer".equals(body.role())) {
            return ResponseEntity.status(403).body(Map.of("detail", "App admins can only create app_developer users"));
        }
        return ResponseEntity.ok(userService.createUser(body));
    }

    @DeleteMapping("/{userId}")
    public ResponseEntity<?> deleteUser(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer userId) {
        if (!isLogosAdmin(auth)) return forbidden();
        if (!userService.deleteUser(userId)) {
            return ResponseEntity.status(404).body(Map.of("detail", "User not found"));
        }
        return ResponseEntity.ok(Map.of("message", "User deleted"));
    }

    @PatchMapping("/{userId}/role")
    public ResponseEntity<?> patchUserRole(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer userId,
            @RequestBody UpdateUserRoleRequest body) {
        if (!isLogosAdmin(auth)) return forbidden();
        return userService.updateRole(userId, body.role())
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElse(ResponseEntity.status(404).body(null));
    }

    @PatchMapping("/{userId}")
    public ResponseEntity<?> patchUserInfo(
            @RequestAttribute("authContext") AuthContext auth,
            @PathVariable Integer userId,
            @RequestBody UpdateUserInfoRequest body) {
        if (!isAppAdminOrAbove(auth)) return forbidden();
        return userService.updateInfo(userId, body)
            .<ResponseEntity<?>>map(ResponseEntity::ok)
            .orElse(ResponseEntity.status(404).body(null));
    }

    @PostMapping("/import")
    public ResponseEntity<?> importUsers(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestParam("file") org.springframework.web.multipart.MultipartFile file) {
        if (!isAppAdminOrAbove(auth)) return forbidden();
        if (!file.getOriginalFilename().endsWith(".csv")) {
            return ResponseEntity.status(400).body(Map.of("detail", "Only .csv files are accepted."));
        }
        try {
            return ResponseEntity.ok(Map.of("results", userService.importUsers(file)));
        } catch (Exception e) {
            return ResponseEntity.status(400).body(Map.of("error", e.getMessage()));
        }
    }

    static boolean isAppAdminOrAbove(AuthContext auth) {
        return "app_admin".equals(auth.role()) || "logos_admin".equals(auth.role());
    }

    static boolean isLogosAdmin(AuthContext auth) {
        return "logos_admin".equals(auth.role());
    }

    static ResponseEntity<Map<String, String>> forbidden() {
        return ResponseEntity.status(403).body(Map.of("detail", "Insufficient permissions"));
    }
}
