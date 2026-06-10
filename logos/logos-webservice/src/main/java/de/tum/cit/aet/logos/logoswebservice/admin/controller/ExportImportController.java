package de.tum.cit.aet.logos.logoswebservice.admin.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.admin.dto.ImportRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.admin.service.ExportImportService;

@RestController
@RequestMapping("/logosdb")
public class ExportImportController {

    private final ExportImportService service;

    public ExportImportController(ExportImportService service) {
        this.service = service;
    }

    @PostMapping("/export")
    @PreAuthorize("hasAuthority('logos_admin')")
    public ResponseEntity<?> export() {
        return ResponseEntity.ok(service.export());
    }

    @PostMapping("/import")
    @PreAuthorize("hasAuthority('logos_admin')")
    public ResponseEntity<?> importData(
            @RequestBody ImportRequestDTO req) {
        if (req.jsonData() == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "json_data is required"));
        }
        return ResponseEntity.ok(service.importData(req.jsonData()));
    }
}
