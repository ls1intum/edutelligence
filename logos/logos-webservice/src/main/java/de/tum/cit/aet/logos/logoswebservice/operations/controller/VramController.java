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
        // resolution=second serves the raw snapshot cadence (≥1 Hz when the
        // worker pushes per-second telemetry) instead of the default
        // minute/hour downsampling; after_snapshot_id allows cursor-based
        // delta polling, mirroring the vram_delta websocket messages.
        String resolution = body != null ? (String) body.get("resolution") : null;
        int afterSnapshotId = body != null && body.get("after_snapshot_id") instanceof Number n
            ? n.intValue() : 0;
        try {
            return ResponseEntity.ok(vramService.getVramStats(day, afterSnapshotId, resolution));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }
}
