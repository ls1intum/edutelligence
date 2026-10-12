package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.operations.service.PublicStatsService;

/**
 * The public statistics page.
 *
 * <p>Unauthenticated on purpose — the page is a showcase for people who have
 * never logged in — so it answers only what the platform has agreed to show:
 * the successful requests of the teams whose {@code share_public_stats} is
 * true (see {@link PublicStatsService}). The route is permitted in
 * {@code SecurityConfig} rather than guarded here, the same way {@code /info}
 * is: a guard on the method would still let the resource-server chain 401 a
 * request before it reached the controller.
 *
 * <p>The window narrows every number on the page at once, exactly like the
 * statistics page's time range — a filter that moved only some of the
 * aggregates would leave the page contradicting itself.
 */
@RestController
public class PublicStatsController {

    private final PublicStatsService publicStatsService;

    public PublicStatsController(PublicStatsService publicStatsService) {
        this.publicStatsService = publicStatsService;
    }

    @GetMapping("/stats")
    public ResponseEntity<?> publicStats(
            @RequestParam(name = "start_date", required = false) String startDate,
            @RequestParam(name = "end_date", required = false) String endDate) {
        try {
            return ResponseEntity.ok(publicStatsService.getPublicStats(startDate, endDate));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }
}
