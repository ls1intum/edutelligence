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

    /** Unfiltered newest page of the range, without a row count — the live push. */
    public Map<String, Object> getLatestRequests(String startDate, String endDate) {
        return getLatestRequests(startDate, endDate, null, null, null, null,
                                 LATEST_REQUESTS_PAGE_SIZE, false);
    }

    /**
     * One page of the request feed, newest first.
     *
     * <p>Paged by keyset rather than by offset: the caller hands back the
     * {@code (cursorTs, cursorId)} of the last row it received and gets the rows
     * strictly older than it. That makes a page cost the same at any depth, and
     * it does not slide when requests arrive at the top while the operator pages
     * — which an offset does, so an offset page can repeat and skip rows.
     *
     * <p>{@code withTotal} decides whether the range is counted. Counting means
     * scanning it, so the live push — every two seconds for every open
     * statistics session — asks for rows only. It is a page deeper than it
     * renders, which is enough to answer {@code has_more}.
     *
     * @param startDate ISO-8601 start of the window (inclusive); {@code null}
     *                  defaults to 30 days before {@code endDate}
     * @param endDate   ISO-8601 end of the window (inclusive); {@code null}
     *                  defaults to now
     * @param userId    restrict to this requester, or {@code null} for all
     * @param teamId    restrict to this team, or {@code null} for all
     * @param cursorTs  {@code timestamp_request} of the last row already seen;
     *                  {@code null} starts at the newest
     * @param cursorId  {@code request_id} of that row, breaking timestamp ties
     * @param limit     rows to return, clamped to 1..50
     */
    public Map<String, Object> getLatestRequests(String startDate, String endDate,
                                                 Integer userId, Integer teamId,
                                                 String cursorTs, String cursorId,
                                                 int limit, boolean withTotal) {
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

        // An unparseable cursor must not silently jump back to the newest page —
        // the operator would page forward and land where they started. Drop the
        // id along with it so the query sees no cursor at all rather than half of
        // one, and let the caller notice the page repeat.
        ZonedDateTime cursorDt = parseInstantOrNull(cursorTs);
        Timestamp cursor = cursorDt != null ? Timestamp.from(cursorDt.toInstant()) : null;
        String cursorRequestId = cursor != null ? (cursorId != null ? cursorId : "") : null;

        // One row beyond the page: its presence is the has_more answer, and it is
        // dropped before the rows go out.
        List<Map<String, Object>> fetched = logEntryRepository
            .findLatestRequests(startTs, endTs, userId, teamId, cursor, cursorRequestId, pageSize + 1)
            .stream()
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

        boolean hasMore = fetched.size() > pageSize;
        List<Map<String, Object>> rows = hasMore ? fetched.subList(0, pageSize) : fetched;

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("requests", rows);
        result.put("limit", pageSize);
        result.put("has_more", hasMore);
        // The cursor to ask for the next page with. Null on the last page so the
        // caller cannot page past the end.
        if (hasMore && !rows.isEmpty()) {
            Map<String, Object> last = rows.get(rows.size() - 1);
            result.put("next_cursor", Map.of(
                "ts", String.valueOf(last.get("enqueue_ts")),
                "request_id", String.valueOf(last.get("request_id"))));
        } else {
            result.put("next_cursor", null);
        }
        if (withTotal) {
            Long total = logEntryRepository.countRequestsInRange(startTs, endTs, userId, teamId);
            // The feed shows a window onto the range, so it has to say how big
            // the range is — "1-10 of 4,312" is the difference between a capped
            // list and a list the operator reads as complete.
            result.put("total", total != null ? total : 0L);
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

    private static String ts(Instant t) {
        return t != null ? t.toString() : null;
    }
}
