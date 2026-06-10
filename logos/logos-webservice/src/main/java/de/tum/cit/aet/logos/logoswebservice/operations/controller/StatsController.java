package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.operations.service.StatsService;

@RestController
@RequestMapping("/logosdb")
public class StatsController {

    private final StatsService statsService;

    public StatsController(StatsService statsService) {
        this.statsService = statsService;
    }

    @PostMapping("/generalstats")
    public ResponseEntity<?> generalStats(@RequestAttribute("authContext") AuthContext auth) {
        return ResponseEntity.ok(statsService.generalStats());
    }
}
