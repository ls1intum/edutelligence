package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.operations.dto.ModelBenchmarkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.operations.dto.ProviderPerformanceRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.operations.service.ProviderPerformanceService;

@RestController
@RequestMapping("/logosdb")
public class ProviderPerformanceController {

    private final ProviderPerformanceService providerPerformanceService;

    public ProviderPerformanceController(ProviderPerformanceService providerPerformanceService) {
        this.providerPerformanceService = providerPerformanceService;
    }

    @PostMapping("/provider_performance")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> providerPerformance(
            @RequestBody(required = false) ProviderPerformanceRequestDTO request) {
        try {
            return ResponseEntity.ok(providerPerformanceService.getProviderPerformance(request));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/model_benchmarks")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> modelBenchmarks(@RequestBody ModelBenchmarkRequestDTO request) {
        try {
            return ResponseEntity.ok(providerPerformanceService.getModelBenchmarks(request.modelId()));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }
}
