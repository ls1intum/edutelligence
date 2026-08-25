package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.io.IOException;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.dto.ProviderPerformanceRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.operations.dto.StoreModelBenchmarkRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ModelProviderBenchmarkProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ProviderPerformanceProjection;

@Service
public class ProviderPerformanceService {

    private static final Duration DEFAULT_WINDOW = Duration.ofHours(24);
    private static final TypeReference<Map<String, Object>> JSON_MAP = new TypeReference<>() {};

    private final LogEntryRepository logEntryRepository;
    private final ModelProviderRepository modelProviderRepository;
    private final ObjectMapper objectMapper;

    public ProviderPerformanceService(LogEntryRepository logEntryRepository,
                                      ModelProviderRepository modelProviderRepository,
                                      ObjectMapper objectMapper) {
        this.logEntryRepository = logEntryRepository;
        this.modelProviderRepository = modelProviderRepository;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> getProviderPerformance(ProviderPerformanceRequestDTO request) {
        Instant to = request != null && request.to() != null ? request.to() : Instant.now();
        Instant from = request != null && request.from() != null ? request.from() : to.minus(DEFAULT_WINDOW);

        if (!from.isBefore(to)) {
            throw new IllegalArgumentException("from must be before to");
        }

        Integer providerId = request != null ? request.providerId() : null;
        Integer modelId = request != null ? request.modelId() : null;
        List<Map<String, Object>> pairs = logEntryRepository.findProviderPerformance(
                Timestamp.from(from), Timestamp.from(to), providerId, modelId)
            .stream()
            .map(ProviderPerformanceService::toMap)
            .toList();

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("from", from);
        response.put("to", to);
        response.put("pairs", pairs);
        return response;
    }

    public Map<String, Object> getModelBenchmarks(Integer modelId) {
        if (modelId == null || modelId <= 0) {
            throw new IllegalArgumentException("model_id must be a positive integer");
        }

        List<Map<String, Object>> benchmarks = modelProviderRepository.findBenchmarksForModel(modelId)
            .stream()
            .map(this::benchmarkToMap)
            .toList();

        return Map.of("benchmarks", benchmarks);
    }

    public Map<String, Object> storeModelBenchmark(StoreModelBenchmarkRequestDTO request) {
        if (request.modelProviderId() == null || request.modelProviderId() <= 0) {
            throw new IllegalArgumentException("model_provider_id must be a positive integer");
        }
        if (!modelProviderRepository.existsById(request.modelProviderId())) {
            throw new IllegalArgumentException("model_provider_id does not exist");
        }
        if (request.configuration() == null) {
            throw new IllegalArgumentException("configuration is required");
        }
        if (request.dataset() == null || request.dataset().isBlank()) {
            throw new IllegalArgumentException("dataset is required");
        }
        if (request.sampleSize() == null || request.sampleSize() <= 0) {
            throw new IllegalArgumentException("sample_size must be a positive integer");
        }
        validateSuccessfulGuideLlmMetrics(request.metrics());

        int inserted = modelProviderRepository.insertBenchmark(
            request.modelProviderId(),
            toJson(request.configuration()),
            request.dataset().trim(),
            request.sampleSize(),
            toJson(request.metrics()),
            request.recordedAt()
        );
        return Map.of("stored", inserted == 1);
    }

    private static Map<String, Object> toMap(ProviderPerformanceProjection p) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("provider_id", p.getProviderId());
        result.put("provider_name", p.getProviderName());
        result.put("model_id", p.getModelId());
        result.put("model_name", p.getModelName());
        result.put("request_count", p.getRequestCount());
        result.put("successful_request_count", p.getSuccessfulRequestCount());
        result.put("success_rate", p.getSuccessRate());
        result.put("cold_start_count", p.getColdStartCount());
        result.put("cold_start_rate", p.getColdStartRate());
        result.put("ttft_ms", percentiles(p.getTtftP50Ms(), p.getTtftP95Ms(), p.getTtftP100Ms()));
        result.put("tpot_ms", percentiles(p.getTpotP50Ms(), p.getTpotP95Ms(), p.getTpotP100Ms()));
        result.put("ttlt_ms", percentiles(p.getTtltP50Ms(), p.getTtltP95Ms(), p.getTtltP100Ms()));
        return result;
    }

    private static Map<String, Double> percentiles(Double p50, Double p95, Double p100) {
        Map<String, Double> result = new LinkedHashMap<>();
        result.put("p50", p50);
        result.put("p95", p95);
        result.put("p100", p100);
        return result;
    }

    private Map<String, Object> benchmarkToMap(ModelProviderBenchmarkProjection benchmark) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", benchmark.getId());
        result.put("model_provider_id", benchmark.getModelProviderId());
        result.put("provider_id", benchmark.getProviderId());
        result.put("provider_name", benchmark.getProviderName());
        result.put("model_id", benchmark.getModelId());
        result.put("model_name", benchmark.getModelName());
        result.put("configuration", parseJson(benchmark.getConfigurationJson()));
        result.put("dataset", benchmark.getDataset());
        result.put("sample_size", benchmark.getSampleSize());
        result.put("metrics", parseJson(benchmark.getMetricsJson()));
        result.put("recorded_at", benchmark.getRecordedAt());
        return result;
    }

    private Map<String, Object> parseJson(String json) {
        try {
            return objectMapper.readValue(json, JSON_MAP);
        } catch (IOException e) {
            throw new IllegalStateException("Stored benchmark JSON is invalid", e);
        }
    }

    private String toJson(Map<String, Object> value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (IOException e) {
            throw new IllegalArgumentException("Benchmark JSON is invalid", e);
        }
    }

    private static void validateSuccessfulGuideLlmMetrics(Map<String, Object> metrics) {
        if (metrics == null || !(metrics.get("request_totals") instanceof Map<?, ?> totals)) {
            throw new IllegalArgumentException("GuideLLM metrics.request_totals is required");
        }

        int successful = intValue(totals.get("successful"));
        int incomplete = intValue(totals.get("incomplete"));
        int errored = intValue(totals.get("errored"));
        if (successful <= 0 || incomplete > 0 || errored > 0) {
            throw new IllegalArgumentException("Only successful GuideLLM benchmark summaries are stored");
        }
    }

    private static int intValue(Object value) {
        return value instanceof Number number ? number.intValue() : 0;
    }
}
