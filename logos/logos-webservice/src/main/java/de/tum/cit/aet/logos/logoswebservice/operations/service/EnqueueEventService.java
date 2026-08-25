package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.operations.repository.EnqueueEventProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;

@Service
public class EnqueueEventService {

    private final LogEntryRepository logEntryRepository;

    public EnqueueEventService(LogEntryRepository logEntryRepository) {
        this.logEntryRepository = logEntryRepository;
    }

    /**
     * Enqueue events in a range, optionally narrowed to a team or requester.
     *
     * The scope belongs here and not only on the aggregates: the statistics page
     * builds its request-volume chart client-side from these events, so leaving
     * them unfiltered would draw platform-wide bars above filtered totals.
     * Null for either id means "everyone".
     */
    public Map<String, Object> getInRange(String startIso, String endIso, int limit,
                                          Integer userId, Integer teamId) {
        Instant start = parseIso(startIso);
        Instant end = parseIso(endIso);
        List<EnqueueEventProjection> rows = logEntryRepository.findInRange(
            Timestamp.from(start), Timestamp.from(end), userId, teamId, limit);
        return buildResult(rows, null, "");
    }

    public Map<String, Object> getDeltas(String afterEnqueueTs, String afterRequestId,
                                         String untilTs, int limit,
                                         Integer userId, Integer teamId) {
        Instant until = untilTs != null ? parseIso(untilTs) : Instant.now();
        String cursorId = afterRequestId != null ? afterRequestId : "";

        List<EnqueueEventProjection> rows;
        if (afterEnqueueTs == null || afterEnqueueTs.isBlank()) {
            rows = logEntryRepository.findDeltasNoCursor(Timestamp.from(until), userId, teamId, limit);
        } else {
            Instant cursor = parseIso(afterEnqueueTs);
            rows = logEntryRepository.findDeltasWithCursor(
                Timestamp.from(cursor), cursorId, Timestamp.from(until), userId, teamId, limit);
        }
        return buildResult(rows, afterEnqueueTs, cursorId);
    }

    private Map<String, Object> buildResult(List<EnqueueEventProjection> rows,
                                            String initialCursorTs, String initialCursorId) {
        List<Map<String, Object>> events = new ArrayList<>();
        String cursorTs = initialCursorTs;
        String cursorId = initialCursorId;

        for (EnqueueEventProjection row : rows) {
            Instant ts = row.getEnqueueTs();
            String rid = row.getRequestId();
            if (ts == null || rid == null) continue;

            String privacy = row.getPrivacyLevel();
            boolean isCloud = privacy != null && !"LOCAL".equals(privacy);

            Map<String, Object> e = new LinkedHashMap<>();
            e.put("request_id", rid);
            e.put("enqueue_ts", ts.toString());
            e.put("timestamp_ms", ts.toEpochMilli());
            e.put("is_cloud", isCloud);
            events.add(e);

            cursorTs = ts.toString();
            cursorId = rid;
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("events", events);
        result.put("cursor", Map.of(
            "enqueue_ts", cursorTs != null ? cursorTs : "",
            "request_id", cursorId
        ));
        return result;
    }

    private static Instant parseIso(String iso) {
        if (iso == null || iso.isBlank()) return Instant.now();
        try { return Instant.parse(iso); }
        catch (Exception e) { return ZonedDateTime.parse(iso).toInstant(); }
    }
}
