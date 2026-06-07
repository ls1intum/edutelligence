package de.tum.cit.aet.logos.logoswebservice.admin.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.admin.service.AdminUtilService;
import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;

@RestController
@RequestMapping("/logosdb")
public class AdminUtilController {

    private final AdminUtilService service;

    public AdminUtilController(AdminUtilService service) {
        this.service = service;
    }

    @PostMapping("/get_role")
    public ResponseEntity<?> getRole(@RequestAttribute("authContext") AuthContext auth) {
        String role = "logos_admin".equals(auth.role()) ? "root" : "entity";
        return ResponseEntity.ok(Map.of("role", role));
    }

    @PostMapping("/get_api_key_id")
    public ResponseEntity<?> getApiKeyId(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(Map.of("result", auth.apiKeyId()));
    }

    @PostMapping("/set_log")
    public ResponseEntity<?> setLog(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody Map<String, Object> body) {
        Integer targetId = body.get("api_key_id") instanceof Number n ? n.intValue()
                         : body.get("process_id") instanceof Number n ? n.intValue() : null;
        String level = (String) body.get("set_log");
        if (targetId == null || level == null) {
            return ResponseEntity.badRequest().body(
                Map.of("error", "api_key_id (or process_id) and set_log are required"));
        }
        if (!targetId.equals(auth.apiKeyId()) && !"logos_admin".equals(auth.role())) {
            return ResponseEntity.status(403).body(Map.of("error", "Missing authentication to set log"));
        }
        return ResponseEntity.ok(service.setLog(targetId, level));
    }
}