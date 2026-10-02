package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Per-replica relay occupancy for the gateway concurrency benchmark.
 *
 * <p>Not routed through Traefik; the benchmark reaches each replica on the
 * compose network (or via {@code docker run --network container:...}).
 */
@RestController
@RequestMapping("/internal/gateway_relay_stats")
public class GatewayRelayStatsController {

    @GetMapping
    public Map<String, Object> stats() {
        return GatewayRelayOccupancy.snapshot();
    }

    @PostMapping("/reset")
    public ResponseEntity<Map<String, Object>> reset() {
        GatewayRelayOccupancy.resetStep();
        return ResponseEntity.ok(GatewayRelayOccupancy.snapshot());
    }
}
