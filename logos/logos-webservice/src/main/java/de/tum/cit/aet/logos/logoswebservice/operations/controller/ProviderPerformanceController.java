package de.tum.cit.aet.logos.logoswebservice.operations.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.operations.dto.DeleteModelBenchmarkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.operations.dto.ModelBenchmarkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.operations.dto.ProviderPerformanceRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.operations.dto.RunModelBenchmarkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.operations.dto.StoreModelBenchmarkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.operations.service.ProviderPerformanceService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorWorkerAdminClient;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

@RestController
@RequestMapping("/logosdb")
public class ProviderPerformanceController {

    private final ProviderPerformanceService providerPerformanceService;
    private final OrchestratorWorkerAdminClient orchestratorWorkerAdminClient;
    private final ObjectMapper objectMapper;

    public ProviderPerformanceController(ProviderPerformanceService providerPerformanceService,
                                         OrchestratorWorkerAdminClient orchestratorWorkerAdminClient,
                                         ObjectMapper objectMapper) {
        this.providerPerformanceService = providerPerformanceService;
        this.orchestratorWorkerAdminClient = orchestratorWorkerAdminClient;
        this.objectMapper = objectMapper;
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

    @PostMapping("/model_benchmarks/import")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> importModelBenchmark(@RequestBody StoreModelBenchmarkRequestDTO request) {
        try {
            return ResponseEntity.ok(providerPerformanceService.storeModelBenchmark(request));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/model_benchmarks/delete")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> deleteModelBenchmark(@RequestBody DeleteModelBenchmarkRequestDTO request) {
        try {
            return ResponseEntity.ok(providerPerformanceService.deleteModelBenchmark(request.id()));
        } catch (IllegalArgumentException e) {
            int status = request.id() == null || request.id() <= 0 ? 400 : 404;
            return ResponseEntity.status(status).body(Map.of("error", e.getMessage()));
        }
    }

    @PostMapping("/model_benchmarks/run")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> runModelBenchmark(@RequestBody RunModelBenchmarkRequestDTO request) {
        if (request.modelProviderId() == null || request.modelProviderId() <= 0) {
            return ResponseEntity.badRequest().body(Map.of("error", "model_provider_id must be a positive integer"));
        }
        int sampleSize = request.sampleSize() == null ? 5 : request.sampleSize();
        int maxOutputTokens = request.maxOutputTokens() == null ? 512 : request.maxOutputTokens();
        if (sampleSize <= 0 || sampleSize > 100) {
            return ResponseEntity.badRequest().body(Map.of("error", "sample_size must be between 1 and 100"));
        }
        if (maxOutputTokens <= 0 || maxOutputTokens > 4096) {
            return ResponseEntity.badRequest().body(Map.of("error", "max_output_tokens must be between 1 and 4096"));
        }
        try {
            return orchestratorWorkerAdminClient.startModelBenchmark(
                request.modelProviderId(), sampleSize, maxOutputTokens);
        } catch (HttpStatusCodeException e) {
            return ResponseEntity.status(e.getStatusCode()).body(orchestratorError(e));
        } catch (RuntimeException e) {
            return ResponseEntity.status(503).body(Map.of("error", "Benchmark service is unavailable"));
        }
    }

    @PostMapping("/model_benchmarks/cancel")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> cancelModelBenchmark(@RequestBody DeleteModelBenchmarkRequestDTO request) {
        if (request.id() == null || request.id() <= 0) {
            return ResponseEntity.badRequest().body(Map.of("error", "id must be a positive integer"));
        }
        try {
            return orchestratorWorkerAdminClient.cancelModelBenchmark(request.id());
        } catch (HttpStatusCodeException e) {
            return ResponseEntity.status(e.getStatusCode()).body(orchestratorError(e));
        } catch (RuntimeException e) {
            return ResponseEntity.status(503).body(Map.of("error", "Benchmark service is unavailable"));
        }
    }

    private Map<String, Object> orchestratorError(HttpStatusCodeException exception) {
        try {
            return objectMapper.readValue(exception.getResponseBodyAsString(), new TypeReference<>() {});
        } catch (Exception ignored) {
            return Map.of("error", "Benchmark request failed");
        }
    }
}
