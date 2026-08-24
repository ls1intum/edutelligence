package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
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

    /** Rows the live feed pushes, and the page size of a "load older" step. */
    public static final int LATEST_REQUESTS_PAGE_SIZE = 10;

    /** Ceiling on a single page, so a hand-written call can't ask for the world. */
    private static final int LATEST_REQUESTS_MAX_PAGE_SIZE = 50;

    private final LogEntryRepository logEntryRepository;

    public RequestLogService(LogEntryRepository logEntryRepository) {
        this.logEntryRepository = logEntryRepository;
    }

    /**
     * The newest page of the range, without a row count.
     *
     * This is the websocket's push, which runs every two seconds for every open
     * statistics session. {@code log_entry} carries no index on its timestamps,
     * so counting the range means scanning it — the page's own size is all the
     * live feed needs, and the statistics totals already state the range count.
     *
     * @param startDate ISO-8601 start of the window (inclusive); {@code null}
     *                  defaults to 30 days before {@code endDate}
     * @param endDate   ISO-8601 end of the window (inclusive); {@code null}
     *                  defaults to now
     */
    public Map<String, Object> getLatestRequests(String startDate, String endDate) {
        return getLatestRequests(startDate, endDate, LATEST_REQUESTS_PAGE_SIZE, 0, false);
    }

    /**
     * One page of the range plus its row count, for the operator paging back
     * through the history on demand.
     *
     * @param limit  rows to return, clamped to 1..50
     * @param offset rows to skip, newest first — how the UI walks backwards
     *               through the range without widening the live push
     */
    public Map<String, Object> getLatestRequests(String startDate, String endDate, int limit, int offset) {
        return getLatestRequests(startDate, endDate, limit, offset, true);
    }

    private Map<String, Object> getLatestRequests(String startDate, String endDate,
                                                  int limit, int offset, boolean withTotal) {
        ZonedDateTime endDt = parseInstantOrNow(endDate);
        // Same lenient parse as the end: a malformed range must fall back to the
        // default window, not surface as a 500.
        ZonedDateTime startDt = parseInstantOrNull(startDate);
        if (startDt == null || startDt.isAfter(endDt)) {
            startDt = endDt.minusDays(30);
        }
        Timestamp startTs = Timestamp.from(startDt.toInstant());
        Timestamp endTs = Timestamp.from(endDt.toInstant());

        int pageSize = Math.max(1, Math.min(LATEST_REQUESTS_MAX_PAGE_SIZE, limit));
        int skip = Math.max(0, offset);

        List<Map<String, Object>> rows = logEntryRepository.findLatestRequests(startTs, endTs, pageSize, skip).stream()
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("request_id", p.getRequestId());
                m.put("model_name", p.getModelName());
                m.put("provider_name", p.getProviderName());
                m.put("is_cloud", isCloudProviderType(p.getProviderType()));
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
                m.put("team_name", p.getTeamName());
                m.put("username", p.getUsername());
                m.put("full_name", p.getFullName());
                m.put("prompt_tokens", p.getPromptTokens());
                m.put("completion_tokens", p.getCompletionTokens());
                m.put("total_tokens", p.getTotalTokens());
                m.put("cost_microcents", p.getCostMicroCents());
                return m;
            })
            .toList();

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("requests", rows);
        result.put("offset", skip);
        result.put("limit", pageSize);
        if (withTotal) {
            Long total = logEntryRepository.countRequestsInRange(startTs, endTs);
            if (total == null) total = 0L;
            // The feed shows a window onto the range, so it has to say how big
            // the range is — "10 of 4,312" is the difference between a capped
            // list and a list the operator reads as complete.
            result.put("total", total);
            result.put("has_more", (long) skip + rows.size() < total);
        } else {
            // A short page is the end of the range; a full one may not be.
            result.put("has_more", rows.size() >= pageSize);
        }
        return result;
    }

    private static ZonedDateTime parseInstantOrNow(String iso) {
        ZonedDateTime parsed = parseInstantOrNull(iso);
        return parsed != null ? parsed : ZonedDateTime.now(ZoneOffset.UTC);
    }

    private static ZonedDateTime parseInstantOrNull(String iso) {
        if (iso == null || iso.isBlank()) return null;
        try {
            return ZonedDateTime.parse(iso).withZoneSameInstant(ZoneOffset.UTC);
        } catch (Exception e) {
            return null;
        }
    }

    private static boolean isCloudProviderType(String providerType) {
        return providerType != null && !providerType.isEmpty()
               && !providerType.equalsIgnoreCase("logosnode")
               && !providerType.equalsIgnoreCase("ollama");
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
                boolean isCloud = isCloudProviderType(p.getProviderType());
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
                m.put("team_name", p.getTeamName());
                m.put("username", p.getUsername());
                m.put("environment", p.getEnvironment());
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
