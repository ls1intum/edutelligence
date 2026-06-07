package de.tum.cit.aet.logos.logoswebservice.admin.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.admin.service.ExportImportService;
import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;

@RestController
@RequestMapping("/logosdb")
public class ExportImportController {

    private final ExportImportService service;

    public ExportImportController(ExportImportService service) {
        this.service = service;
    }

    @PostMapping("/export")
    public ResponseEntity<?> export(@RequestAttribute("authContext") AuthContext auth) {
        if (!isLogosAdmin(auth)) return forbidden();
        return ResponseEntity.ok(service.export());
    }

    @PostMapping("/import")
    public ResponseEntity<?> importData(
            @RequestAttribute("authContext") AuthContext auth,
            @RequestBody Map<String, Object> body) {
        if (!isLogosAdmin(auth)) return forbidden();
        @SuppressWarnings("unchecked")
        Map<String, Object> jsonData = (Map<String, Object>) body.get("json_data");
        if (jsonData == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "json_data is required"));
        }
        return ResponseEntity.ok(service.importData(jsonData));
    }

    private static boolean isLogosAdmin(AuthContext auth) {
        return "logos_admin".equals(auth.role());
    }

    private static ResponseEntity<?> forbidden() {
        return ResponseEntity.status(403).body(Map.of("detail", "Forbidden"));
    }
}