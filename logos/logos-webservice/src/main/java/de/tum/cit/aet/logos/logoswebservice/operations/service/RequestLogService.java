package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.time.Instant;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.PaginatedRequestProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.RequestLogProjection;

@Service
public class RequestLogService {

    private final LogEntryRepository logEntryRepository;

    public RequestLogService(LogEntryRepository logEntryRepository) {
        this.logEntryRepository = logEntryRepository;
    }

    public Map<String, Object> getLatestRequests() {
        List<Map<String, Object>> rows = logEntryRepository.findLatestRequests().stream()
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("request_id", p.getRequestId());
                m.put("model_name", p.getModelName());
                m.put("provider_name", p.getProviderName());
                m.put("status", p.getResultStatus() != null ? p.getResultStatus() : "pending");
                m.put("timestamp", ts(p.getTimestampRequest()));
                m.put("enqueue_ts", ts(p.getTimestampRequest()));
                m.put("scheduled_ts", ts(p.getTimestampForwarding()));
                m.put("request_complete_ts", ts(p.getTimestampResponse()));
                m.put("duration", p.getRunSeconds());
                m.put("cold_start", p.getWasColdStart());
                m.put("queue_seconds", p.getQueueSeconds());
                m.put("total_seconds", p.getTotalSeconds());
                m.put("initial_priority", p.getInitialPriority());
                m.put("priority_when_scheduled", p.getPriorityWhenScheduled());
                m.put("queue_depth_at_enqueue", p.getQueueDepthAtEnqueue());
                m.put("error_message", p.getErrorMessage());
                return m;
            })
            .toList();
        return Map.of("requests", rows);
    }

    /**
     * @param userId restrict to requests by this user (across all their api
     *               keys); {@code null} (admin callers) resolves ids globally.
     */
    public Map<String, Object> getRequestLogs(Integer userId, List<String> requestIds) {
        if (requestIds.isEmpty()) {
            return Map.of("requests", Collections.emptyList(), "missing_request_ids", Collections.emptyList());
        }

        List<RequestLogProjection> projections = userId != null
            ? logEntryRepository.findRequestLogsByUser(userId, requestIds)
            : logEntryRepository.findRequestLogs(null, requestIds);
        List<Map<String, Object>> rows = projections.stream()
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("request_id", p.getRequestId());
                m.put("status", p.getResultStatus() != null ? p.getResultStatus() : "pending");
                m.put("provider_name", p.getProviderName());
                m.put("model_name", p.getModelName());
                m.put("enqueue_ts", ts(p.getEnqueueTs()));
                m.put("scheduled_ts", ts(p.getScheduledTs()));
                m.put("request_complete_ts", ts(p.getRequestCompleteTs()));
                m.put("ttft_ms", p.getTtftMs());
                m.put("total_latency_ms", p.getTotalLatencyMs());
                m.put("queue_wait_ms", p.getQueueWaitMs());
                m.put("processing_ms", p.getProcessingMs());
                m.put("cold_start", p.getColdStart());
                m.put("queue_depth_at_arrival", p.getQueueDepthAtArrival());
                m.put("utilization_at_arrival", p.getUtilizationAtArrival());
                m.put("queue_depth_at_schedule", p.getQueueDepthAtSchedule());
                m.put("priority_when_scheduled", p.getPriorityWhenScheduled());
                m.put("load_duration_ms", p.getLoadDurationMs());
                m.put("available_vram_mb", p.getAvailableVramMb());
                m.put("azure_rate_remaining_requests", p.getAzureRateRemainingRequests());
                m.put("azure_rate_remaining_tokens", p.getAzureRateRemainingTokens());
                m.put("error_message", p.getErrorMessage());
                m.put("prompt_tokens", p.getPromptTokens());
                m.put("completion_tokens", p.getCompletionTokens());
                m.put("total_tokens", p.getTotalTokens());
                return m;
            })
            .toList();

        List<String> foundIds = rows.stream()
            .map(r -> (String) r.get("request_id"))
            .collect(Collectors.toList());
        List<String> missing = requestIds.stream()
            .filter(id -> !foundIds.contains(id))
            .collect(Collectors.toList());
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("requests", rows);
        result.put("missing_request_ids", missing);
        return result;
    }

    /**
     * @param userId restrict to requests by this user (across all their api
     *               keys); {@code null} (admin callers) returns requests
     *               across all users, matching the live request feed on the
     *               statistics page.
     */
    public Map<String, Object> getPaginatedRequests(Integer userId, int page, int perPage) {
        page = Math.max(1, page);
        perPage = Math.max(1, Math.min(100, perPage));
        long offsetLong = (long) (page - 1) * perPage;
        int offset = offsetLong > Integer.MAX_VALUE ? Integer.MAX_VALUE : (int) offsetLong;

        Long total = userId != null
            ? logEntryRepository.countByUserId(userId)
            : logEntryRepository.countAllRequests();
        if (total == null) total = 0L;
        int totalPages = Math.max(1, (int) ((total + perPage - 1) / perPage));

        List<PaginatedRequestProjection> projections = userId != null
            ? logEntryRepository.findPaginatedRequestsByUser(userId, perPage, offset)
            : logEntryRepository.findPaginatedRequests(null, perPage, offset);
        List<Map<String, Object>> rows = projections.stream()
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                String pt = p.getProviderType();
                boolean isCloud = pt != null && !pt.equalsIgnoreCase("logosnode")
                                             && !pt.equalsIgnoreCase("ollama")
                                             && !pt.isEmpty();
                m.put("request_id", p.getRequestId());
                m.put("model_name", p.getModelName());
                m.put("provider_name", p.getProviderName());
                m.put("is_cloud", isCloud);
                m.put("status", p.getResultStatus() != null ? p.getResultStatus() : "pending");
                m.put("timestamp", ts(p.getEnqueueTs()));
                m.put("enqueue_ts", ts(p.getEnqueueTs()));
                m.put("scheduled_ts", ts(p.getScheduledTs()));
                m.put("request_complete_ts", ts(p.getRequestCompleteTs()));
                m.put("duration", p.getRunSeconds());
                m.put("cold_start", p.getColdStart());
                m.put("queue_seconds", p.getQueueSeconds());
                m.put("total_seconds", p.getTotalSeconds());
                m.put("initial_priority", p.getInitialPriority());
                m.put("priority_when_scheduled", p.getPriorityWhenScheduled());
                m.put("queue_depth_at_enqueue", p.getQueueDepthAtEnqueue());
                m.put("error_message", p.getErrorMessage());
                return m;
            })
            .toList();

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("requests", rows);
        result.put("total", total);
        result.put("page", page);
        result.put("per_page", perPage);
        result.put("total_pages", totalPages);
        return result;
    }

    private static String ts(Instant t) {
        return t != null ? t.toString() : null;
    }
}
