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
                request.modelProviderId(), sampleSize, maxOutputTokens, benchmarkSettings(request));
        } catch (HttpStatusCodeException e) {
            return ResponseEntity.status(e.getStatusCode()).body(orchestratorError(e));
        } catch (RuntimeException e) {
            return ResponseEntity.status(503).body(Map.of("error", "Benchmark service is unavailable"));
        }
    }

    private Map<String, Object> benchmarkSettings(RunModelBenchmarkRequestDTO request) {
        Map<String, Object> settings = new java.util.LinkedHashMap<>();
        if (request.dataset() != null) settings.put("dataset", request.dataset());
        if (request.subset() != null) settings.put("subset", request.subset());
        if (request.split() != null) settings.put("split", request.split());
        if (request.textColumn() != null) settings.put("text_column", request.textColumn());
        if (request.profile() != null) settings.put("profile", request.profile());
        if (request.concurrency() != null) settings.put("concurrency", request.concurrency());
        if (request.seed() != null) settings.put("seed", request.seed());
        if (request.servingOverrides() != null) settings.put("serving_overrides", request.servingOverrides());
        return settings;
    }

    @PostMapping("/model_benchmarks/limits")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> benchmarkLimits(@RequestBody Map<String, Object> body) {
        try {
            return orchestratorWorkerAdminClient.benchmarkLimits(body);
        } catch (HttpStatusCodeException e) {
            return ResponseEntity.status(e.getStatusCode()).body(orchestratorError(e));
        } catch (RuntimeException e) {
            return ResponseEntity.status(503).body(Map.of("error", "Worker limits are unavailable"));
        }
    }

    @PostMapping("/model_benchmarks/datasets/search")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> searchDatasets(@RequestBody Map<String, Object> body) {
        return datasetMetadataResponse("search", body);
    }

    @PostMapping("/model_benchmarks/datasets/metadata")
    @PreAuthorize("hasAuthority('" + Role.Names.LOGOS_ADMIN + "')")
    public ResponseEntity<?> datasetMetadata(@RequestBody Map<String, Object> body) {
        return datasetMetadataResponse("metadata", body);
    }

    private ResponseEntity<?> datasetMetadataResponse(String operation, Map<String, Object> body) {
        try {
            return orchestratorWorkerAdminClient.benchmarkDatasets(operation, body);
        } catch (HttpStatusCodeException e) {
            return ResponseEntity.status(e.getStatusCode()).body(orchestratorError(e));
        } catch (RuntimeException e) {
            return ResponseEntity.status(503).body(Map.of("error", "Dataset service is unavailable"));
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
