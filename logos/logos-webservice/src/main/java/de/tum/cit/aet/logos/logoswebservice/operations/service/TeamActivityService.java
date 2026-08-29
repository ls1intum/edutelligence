package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;
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

    private final LogEntryRepository logEntryRepository;
    private final RequestLogService requestLogService;

    public TeamActivityService(LogEntryRepository logEntryRepository,
                               RequestLogService requestLogService) {
        this.logEntryRepository = logEntryRepository;
        this.requestLogService = requestLogService;
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
            userId, teamId, null, cursorTs, cursorId, REQUEST_PAGE_SIZE, true);

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
}
