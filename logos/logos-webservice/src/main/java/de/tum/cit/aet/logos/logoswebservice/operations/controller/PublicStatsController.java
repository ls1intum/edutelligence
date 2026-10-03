package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.common.IpRateLimiterService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.StatsService;

import jakarta.servlet.http.HttpServletRequest;

/**
 * Aggregates behind the public stats page — the one slice of the platform
 * anyone can read without signing in.
 *
 * <p>Like /info it takes no credential, so it is rate limited per source IP.
 * The response is aggregate counts only (team names, no user names, no
 * request rows), and every request figure counts settled successes.
 */
@RestController
@RequestMapping("/public")
public class PublicStatsController {

    private final StatsService statsService;
    private final IpRateLimiterService rateLimiter;

    public PublicStatsController(StatsService statsService, IpRateLimiterService rateLimiter) {
        this.statsService = statsService;
        this.rateLimiter = rateLimiter;
    }

    @GetMapping("/stats")
    public ResponseEntity<Map<String, Object>> stats(HttpServletRequest request) {
        rateLimiter.enforcePublicEndpoint(rateLimiter.clientIp(request), "public_stats");
        return ResponseEntity.ok(statsService.publicStats());
    }
}
