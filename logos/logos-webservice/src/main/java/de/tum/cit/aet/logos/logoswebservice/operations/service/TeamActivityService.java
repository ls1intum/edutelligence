package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogExportProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ScopeOptionProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.TeamActivityProjections;

/**
 * The team-scoped activity view app administrators asked for (issue #776).
 *
 * What is happening right now, what the team has spent, and the requests
 * behind both. Not a second statistics page: the VRAM curves, the lane health
 * and the per-worker GPUs belong to whoever runs the cluster and mean nothing
 * to someone who runs one team on it.
 */
@Service
public class TeamActivityService {

    /**
     * How far back a request may have started and still be counted as in
     * flight.
     *
     * Rows get stranded: a client disconnects, a worker dies mid-stream, and
     * the row never gains a response. It also never expires on its own, so
     * counting every response-less row means counting every such failure since
     * the platform began — one team had 142, all over a day old. Nothing beyond
     * the request timeout can still be running, and this is comfortably past
     * it.
     */
    private static final Duration IN_FLIGHT_HORIZON = Duration.ofMinutes(30);

    /** Default reporting window, and the ceiling on what a caller may ask for. */
    private static final int DEFAULT_DAYS = 7;
    private static final int MAX_DAYS = 90;

    /** Rows of the request list per page. */
    private static final int REQUEST_PAGE_SIZE = 20;

    /**
     * Ceiling of one trace export. A consented team on a busy month can outrun
     * a download that still fits in a browser tab; the export then keeps the
     * newest slice and says so, instead of hanging on a multi-hundred-megabyte
     * file. The caller narrows with a shorter window or the requester filter
     * to get the rest.
     */
    private static final int EXPORT_MAX_ROWS = 10_000;

    private final LogEntryRepository logEntryRepository;
    private final RequestLogService requestLogService;
    private final TeamRepository teamRepository;
    private final ObjectMapper objectMapper;

    public TeamActivityService(LogEntryRepository logEntryRepository,
                               RequestLogService requestLogService,
                               TeamRepository teamRepository,
                               ObjectMapper objectMapper) {
        this.logEntryRepository = logEntryRepository;
        this.requestLogService = requestLogService;
        this.teamRepository = teamRepository;
        this.objectMapper = objectMapper;
    }

    /**
     * Live counts and per-key usage for one team.
     *
     * The caller is responsible for having established that this team is one
     * the requester may look at; nothing here re-checks it.
     */
    public Map<String, Object> getTeamActivity(int teamId, Integer requestedDays,
                                              Integer userId, String cursorTs, String cursorId) {
        int days = clampDays(requestedDays);
        Instant now = Instant.now();
        Timestamp since = Timestamp.from(now.minus(Duration.ofDays(days)));
        Timestamp inFlightSince = Timestamp.from(now.minus(IN_FLIGHT_HORIZON));

        TeamActivityProjections.LiveCountsProjection counts =
            logEntryRepository.findTeamLiveCounts(teamId, since, inFlightSince);

        Map<String, Object> live = new LinkedHashMap<>();
        live.put("queued", counts != null ? counts.getQueued() : 0L);
        live.put("running", counts != null ? counts.getRunning() : 0L);
        live.put("finished", counts != null ? counts.getFinished() : 0L);
        live.put("failed", counts != null ? counts.getFailed() : 0L);

        List<Map<String, Object>> keys =
            logEntryRepository.findTeamKeyUsage(teamId, since).stream()
                .map(TeamActivityService::toKeyUsage)
                .toList();

        long totalTokens = keys.stream()
            .mapToLong(k -> (long) k.getOrDefault("total_tokens", 0L))
            .sum();
        long totalRequests = keys.stream()
            .mapToLong(k -> (long) k.getOrDefault("request_count", 0L))
            .sum();

        // The individual requests behind the counts. Counts alone answer "is
        // anything happening"; the list answers "what", which is the question
        // that follows within seconds of the first one.
        Map<String, Object> requests = requestLogService.getLatestRequests(
            since.toInstant().toString(), now.toString(),
            userId, teamId, cursorTs, cursorId, REQUEST_PAGE_SIZE, true);

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("team_id", teamId);
        payload.put("days", days);
        payload.put("since", since.toInstant().toString());
        payload.put("live", live);
        payload.put("keys", keys);
        payload.put("total_tokens", totalTokens);
        payload.put("total_requests", totalRequests);
        // Who in this team sent anything in the window, for the request
        // filter. Scoped to the team by the query, so it cannot name a
        // requester from elsewhere, and never scoped by userId — this list is
        // the picker, and narrowing it by the current pick would leave no way
        // back to the others.
        payload.put("requesters", toScopeOptions(logEntryRepository.findRequestersWithTraffic(
            since, Timestamp.from(now), teamId)));
        payload.put("requests", requests.get("requests"));
        payload.put("requests_total", requests.get("total"));
        payload.put("requests_has_more", requests.get("has_more"));
        payload.put("requests_next_cursor", requests.get("next_cursor"));
        return payload;
    }

    /**
     * The consent-based traces of one team: every request the orchestrator
     * recorded at FULL privacy within the window, payloads included (issue
     * #667). That is the whole point of the opt-in — the requester agreed to
     * exactly this data being stored, and an administrator of the team is
     * entitled to take it back out.
     *
     * <p>The window and the narrowing rules are the ones of the activity view
     * above, so an export and the list it was started from describe the same
     * slice of traffic. Billing-only rows are not part of the result — the
     * query does not even read their payloads, and there is no content to
     * hand over for them anyway.
     *
     * @param teamId         the team to export; the caller established access
     * @param requestedDays  window, clamped like {@link #getTeamActivity}
     * @param userId         narrow to one requester, or {@code null} for all
     * @return the export envelope: window metadata plus the {@code traces}
     *         array the download is built from
     */
    public Map<String, Object> exportTeamTraces(int teamId, Integer requestedDays, Integer userId) {
        int days = clampDays(requestedDays);
        Instant now = Instant.now();
        Timestamp since = Timestamp.from(now.minus(Duration.ofDays(days)));

        // One row beyond the cap, the same trick the feed uses for has_more:
        // the extra row is the answer to "was anything left behind", and it
        // is dropped before the file goes out.
        List<LogExportProjection> fetched = logEntryRepository.findFullTracesForExport(
            teamId, since, Timestamp.from(now), userId, EXPORT_MAX_ROWS + 1);
        boolean truncated = fetched.size() > EXPORT_MAX_ROWS;
        List<LogExportProjection> rows = truncated
            ? fetched.subList(0, EXPORT_MAX_ROWS)
            : fetched;

        String teamName = teamRepository.findById(teamId).map(Team::getName).orElse(null);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("team_id", teamId);
        result.put("team_name", teamName);
        result.put("days", days);
        result.put("since", since.toInstant().toString());
        result.put("count", rows.size());
        result.put("truncated", truncated);
        result.put("traces", rows.stream().map(this::toTrace).toList());
        return result;
    }

    private Map<String, Object> toTrace(LogExportProjection p) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("request_id", p.getRequestId());
        m.put("timestamp_request", ts(p.getTimestampRequest()));
        m.put("timestamp_forwarding", ts(p.getTimestampForwarding()));
        m.put("timestamp_response", ts(p.getTimestampResponse()));
        m.put("time_at_first_token", ts(p.getTimeAtFirstToken()));
        m.put("privacy_level", p.getPrivacyLevel());
        m.put("model_name", p.getModelName());
        m.put("provider_name", p.getProviderName());
        m.put("provider_type", p.getProviderType());
        m.put("policy_id", p.getPolicyId());
        m.put("environment", p.getEnvironment());
        m.put("api_key_id", p.getApiKeyId());
        m.put("api_key_name", p.getKeyName());
        m.put("username", p.getUsername());
        m.put("full_name", p.getFullName());
        m.put("team_name", p.getTeamName());
        m.put("client_ip", p.getClientIp());
        m.put("status", p.getResultStatus() != null ? p.getResultStatus() : "pending");
        m.put("error_message", p.getErrorMessage());
        m.put("priority", p.getPriority());
        m.put("initial_priority", p.getInitialPriority());
        m.put("priority_when_scheduled", p.getPriorityWhenScheduled());
        m.put("queue_depth_at_enqueue", p.getQueueDepthAtEnqueue());
        m.put("queue_depth_at_schedule", p.getQueueDepthAtSchedule());
        m.put("queue_depth_at_arrival", p.getQueueDepthAtArrival());
        m.put("timeout_s", p.getTimeoutS());
        m.put("utilization_at_arrival", p.getUtilizationAtArrival());
        m.put("queue_wait_ms", p.getQueueWaitMs());
        m.put("was_cold_start", p.getWasColdStart());
        m.put("load_duration_ms", p.getLoadDurationMs());
        m.put("available_vram_mb", p.getAvailableVramMb());
        m.put("azure_rate_remaining_requests", p.getAzureRateRemainingRequests());
        m.put("azure_rate_remaining_tokens", p.getAzureRateRemainingTokens());
        m.put("prompt_tokens", p.getPromptTokens());
        m.put("completion_tokens", p.getCompletionTokens());
        m.put("total_tokens", p.getTotalTokens());
        m.put("cost_microcents", p.getCostMicroCents());
        m.put("classification_statistics", json(p.getClassificationStatistics()));
        m.put("input_payload", json(p.getInputPayload()));
        m.put("headers", json(p.getHeaders()));
        m.put("response_payload", json(p.getResponsePayload()));
        return m;
    }

    /**
     * Back to structured data for the download. The database returns JSONB as
     * text, and a trace whose payload is a string that merely contains JSON
     * is one layer harder to read than it should be. A column that is NULL
     * stays NULL: billing-only rows never reached this method, but a FULL
     * request whose response was never stored must still read as absent
     * rather than as an empty object.
     */
    private Object json(String text) {
        if (text == null || text.isBlank()) return null;
        try {
            return objectMapper.readValue(text, Object.class);
        } catch (Exception e) {
            // JSONB is valid JSON by construction; reaching this means the
            // column stopped being what the schema says. Keep the raw text
            // rather than dropping the trace's data.
            return text;
        }
    }

    private static List<Map<String, Object>> toScopeOptions(List<ScopeOptionProjection> rows) {
        return rows.stream()
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("id", p.getId());
                m.put("label", p.getLabel());
                m.put("requestCount", p.getRequestCount());
                return m;
            })
            .toList();
    }

    private static Map<String, Object> toKeyUsage(TeamActivityProjections.KeyUsageProjection p) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("key_id", p.getKeyId());
        m.put("key_name", p.getKeyName());
        m.put("key_type", p.getKeyType());
        m.put("environment", p.getEnvironment());
        m.put("request_count", p.getRequestCount());
        // Null means the key's requests recorded no usage at all — zero is the
        // honest rendering of that for a total, and it keeps the column numeric.
        m.put("total_tokens", p.getTotalTokens() != null ? p.getTotalTokens() : 0L);
        return m;
    }

    private static int clampDays(Integer requested) {
        if (requested == null) return DEFAULT_DAYS;
        return Math.max(1, Math.min(MAX_DAYS, requested));
    }

    private static String ts(Instant t) {
        return t != null ? t.toString() : null;
    }
}
