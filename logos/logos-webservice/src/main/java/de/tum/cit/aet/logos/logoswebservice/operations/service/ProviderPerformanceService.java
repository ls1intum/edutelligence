package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.operations.dto.ProviderPerformanceRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ProviderPerformanceProjection;

@Service
public class ProviderPerformanceService {

    private static final Duration DEFAULT_WINDOW = Duration.ofHours(24);

    private final LogEntryRepository logEntryRepository;

    public ProviderPerformanceService(LogEntryRepository logEntryRepository) {
        this.logEntryRepository = logEntryRepository;
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
}
