package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.operations.service.VramService;

@RestController
public class VramController {

    private final VramService vramService;

    public VramController(VramService vramService) {
        this.vramService = vramService;
    }

    @PostMapping("/logosdb/get_ollama_vram_stats")
    public ResponseEntity<?> getVramStats(@RequestAttribute("authContext") AuthContext auth,
                                          @RequestBody(required = false) Map<String, Object> body) {
        String day = body != null ? (String) body.get("day") : null;
        try {
            return ResponseEntity.ok(vramService.getVramStats(day));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }
}
