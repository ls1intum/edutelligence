package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.io.IOException;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.LogLevel;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogExportProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ScopeOptionProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.TeamActivityProjections;

/**
 * The team-scoped activity view for app administrators.
 *
 * What is happening right now, what the team has spent, and the requests
 * behind both. Not a second statistics page: the VRAM curves, the lane health
 * and the per-worker GPUs belong to whoever runs the cluster and mean nothing
 * to someone who runs one team on it.
 *
 * The view refreshes every few seconds per open tab, so its queries come in
 * two tiers. The live tier — the in-flight counts and the request page — is
 * re-read on every refresh, because that is the point of the view. The period
 * tier — per-key spend, the requester picker, the most asked questions —
 * changes with completed requests, not with the clock, and is served from a
 * short TTL cache: recomputing a ninety-day aggregation on every poll of every
 * open tab is how the view stops loading at all.
 */
@Service
public class TeamActivityService {

    private static final Logger log = LoggerFactory.getLogger(TeamActivityService.class);

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

    /** How many distinct questions the "Most Asked Questions" section shows. */
    private static final int MOST_ASKED_QUESTIONS_LIMIT = 5;

    /**
     * Chunk size of the export's row stream. The download is written row by
     * row into the response, so the service holds one chunk of the window in
     * memory at a time — a chunk of consented rows can carry multi-megabyte
     * payloads, which is why the chunk is small rather than the capped slice.
     */
    private static final int EXPORT_CHUNK_SIZE = 500;

    /**
     * Columns of one trace row, in the order the export writes them — JSON
     * field names and CSV header cells from the same list, so the two formats
     * cannot drift apart.
     */
    private static final String[] TRACE_COLUMNS = {
        "request_id", "timestamp_request", "timestamp_forwarding", "timestamp_response",
        "time_at_first_token", "privacy_level", "model_name", "provider_type",
        "environment", "api_key_id", "api_key_name", "username", "full_name", "team_name",
        "client_ip", "status", "error_message", "priority", "initial_priority",
        "priority_when_scheduled", "queue_depth_at_enqueue", "queue_depth_at_schedule",
        "queue_depth_at_arrival", "timeout_s", "utilization_at_arrival", "queue_wait_ms",
        "was_cold_start", "load_duration_ms", "available_vram_mb", "prompt_tokens",
        "completion_tokens", "total_tokens", "cost_microcents", "classification_statistics",
        "input_payload", "headers", "response_payload",
    };

    private final LogEntryRepository logEntryRepository;
    private final RequestLogService requestLogService;
    private final TeamRepository teamRepository;
    private final ApiKeyRepository apiKeyRepository;
    private final ObjectMapper objectMapper;

    /**
     * Newest rows the most-asked question parser ever looks at. The section is
     * a "what is this team asking" digest, not an audit of the whole window,
     * and parsing the stored JSONB of every consented row of a busy ninety
     * days is the computation that keeps the tab from loading at all. The
     * sample is the newest rows of the window — recency is the point.
     */
    private final int mostAskedScanLimit;

    /**
     * Ceiling of one trace export. A consented team on a busy month can outrun
     * a download that still fits in a spreadsheet; the export then keeps the
     * newest slice, says so in the file and in the response, and the caller
     * narrows with a shorter window or the requester filter to get the rest.
     */
    private final int exportMaxRows;

    /** How long the period tier (see the class javadoc) is trusted without re-reading. */
    private final long aggregateCacheTtlMillis;

    /** Period-tier results per (team, window), trusted for the TTL above. */
    private final ConcurrentHashMap<String, CacheEntry<PeriodAggregates>> aggregatesCache =
        new ConcurrentHashMap<>();

    public TeamActivityService(LogEntryRepository logEntryRepository,
                               RequestLogService requestLogService,
                               TeamRepository teamRepository,
                               ApiKeyRepository apiKeyRepository,
                               ObjectMapper objectMapper,
                               @Value("${logos.team-activity.most-asked-scan-limit:10000}") int mostAskedScanLimit,
                               @Value("${logos.team-activity.export-max-rows:10000}") int exportMaxRows,
                               @Value("${logos.team-activity.aggregate-cache-ttl-seconds:60}") long aggregateCacheTtlSeconds) {
        this.logEntryRepository = logEntryRepository;
        this.requestLogService = requestLogService;
        this.teamRepository = teamRepository;
        this.apiKeyRepository = apiKeyRepository;
        this.objectMapper = objectMapper;
        this.mostAskedScanLimit = mostAskedScanLimit;
        this.exportMaxRows = exportMaxRows;
        this.aggregateCacheTtlMillis = Duration.ofSeconds(aggregateCacheTtlSeconds).toMillis();
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

        // The period tier: served from the TTL cache, because a ninety-day
        // aggregation is not something an open tab should re-pay every poll.
        // None of the three depends on the requester filter, so the window is
        // the whole cache key.
        PeriodAggregates period = periodAggregates(teamId, days, since);

        long totalTokens = period.keys().stream()
            .mapToLong(k -> (long) k.getOrDefault("total_tokens", 0L))
            .sum();
        long totalRequests = period.keys().stream()
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
        // Whether any key of the team is opted into FULL logging, so the view
        // can say before an export is started that the download will hold no
        // request or response content.
        payload.put("full_logging_enabled", hasFullLoggingKey(teamId));
        payload.put("live", live);
        payload.put("keys", period.keys());
        payload.put("total_tokens", totalTokens);
        payload.put("total_requests", totalRequests);
        // Who in this team sent anything in the window, for the request
        // filter. Scoped to the team by the query, so it cannot name a
        // requester from elsewhere, and never scoped by userId — this list is
        // the picker, and narrowing it by the current pick would leave no way
        // back to the others.
        payload.put("requesters", period.requesters());
        payload.put("requests", requests.get("requests"));
        payload.put("requests_total", requests.get("total"));
        payload.put("requests_has_more", requests.get("has_more"));
        payload.put("requests_next_cursor", requests.get("next_cursor"));
        payload.put("most_asked_questions", period.mostAsked());
        return payload;
    }

    /**
     * The period tier behind the activity view, cached for the TTL.
     *
     * Per-key spend, the requester picker and the most asked questions all
     * move on the cadence of completed requests, not of polls — and each of
     * them aggregates the whole window. One entry per (team, window) holds
     * all three so a poll pays at most one lookup and, past the TTL, at most
     * one round of the three queries rather than three lookups of three
     * single-purpose caches.
     */
    private PeriodAggregates periodAggregates(int teamId, int days, Timestamp since) {
        String key = teamId + "|" + days;
        long now = System.currentTimeMillis();
        CacheEntry<PeriodAggregates> cached = aggregatesCache.get(key);
        if (cached != null && now - cached.loadedAtMs() < aggregateCacheTtlMillis) {
            return cached.value();
        }

        List<Map<String, Object>> keys =
            logEntryRepository.findTeamKeyUsage(teamId, since).stream()
                .map(TeamActivityService::toKeyUsage)
                .toList();

        List<Map<String, Object>> requesters = toScopeOptions(
            logEntryRepository.findRequestersWithTraffic(
                since, Timestamp.from(Instant.now()), teamId, null, false));

        // The newest rows of the window, bounded, are what the section ranks:
        // parsing the stored JSONB of every consented row of a busy window is
        // unbounded work for a digest.
        List<Map<String, Object>> mostAsked = logEntryRepository
            .findMostAskedQuestions(since, Timestamp.from(Instant.now()), teamId,
                                    mostAskedScanLimit, MOST_ASKED_QUESTIONS_LIMIT)
            .stream()
            .<Map<String, Object>>map(p -> Map.of("question", p.getQuestion(), "count", p.getAskCount()))
            .toList();

        PeriodAggregates value = new PeriodAggregates(keys, requesters, mostAsked);
        aggregatesCache.put(key, new CacheEntry<>(value, now));
        // The cache is bounded by what is being looked at, not by history:
        // sweep the expired while inserting so a long-lived process does not
        // keep entries for windows nobody polls any more.
        if (aggregatesCache.size() > 128) {
            aggregatesCache.entrySet().removeIf(e -> now - e.getValue().loadedAtMs() >= aggregateCacheTtlMillis);
        }
        return value;
    }

    // ── Trace export ─────────────────────────────────────────────────────────

    /** What the export writes, in which format, and what it will not write. */
    public enum ExportFormat {
        JSON, CSV
    }

    /**
     * Everything the export needs before the first byte goes out.
     *
     * The download is a file, not a JSON body: the caller writes it to the
     * response, and the header fields here are the ones that have to be set
     * before the first byte — how big the window is, whether the file is the
     * whole answer, how many rows it holds.
     */
    public record ExportPrep(
        int teamId,
        Integer userId,
        String teamName,
        int days,
        Instant since,
        Instant now,
        ExportFormat format,
        long totalInWindow,
        /** How many rows the file holds: the window, capped. */
        long count,
        boolean truncated,
        boolean fullLoggingEnabled,
        String note
    ) {
        public String fileName() {
            return "logos-traces-team-" + teamId + "-" + days + "d." + (format == ExportFormat.CSV ? "csv" : "json");
        }
    }

    /**
     * The request traces of one team for the export, everything that has to
     * be known before the file is opened.
     *
     * <p>Every request of the window is in scope — the same slice the
     * activity list shows, so an export is never a mystery of which rows it
     * skipped. The rows the requester consented to (recorded at FULL privacy)
     * carry their request and response content; the billing-only rows come
     * out with the content columns empty, because that is all the platform
     * stored for them.
     *
     * <p>The window may hold more than one export carries: {@code truncated}
     * says that the file is the newest slice of a larger set,
     * {@code totalInWindow} says how large, and the caller surfaces both so a
     * partial download reads as a capped one rather than as a lost one. The
     * {@code note} accompanies the file whenever not a single row of it
     * carries content — a download without an explanation reads as a bug —
     * and it is computed over the slice the file keeps, not the whole window,
     * so "full logging is on" never contradicts "this file has no content".
     */
    public ExportPrep prepareExport(int teamId, Integer requestedDays, Integer userId, String format) {
        int days = clampDays(requestedDays);
        Instant now = Instant.now();
        Timestamp since = Timestamp.from(now.minus(Duration.ofDays(days)));
        Timestamp end = Timestamp.from(now);

        ExportFormat out = "csv".equalsIgnoreCase(format) ? ExportFormat.CSV : ExportFormat.JSON;

        long totalInWindow = valueOrDefault(logEntryRepository.countTracesForExport(teamId, since, end, userId));
        boolean truncated = totalInWindow > exportMaxRows;

        String teamName = teamRepository.findById(teamId).map(Team::getName).orElse(null);
        boolean fullLoggingEnabled = hasFullLoggingKey(teamId);

        String note = null;
        if (valueOrDefault(logEntryRepository.countConsentedInExportSlice(
                teamId, since, end, userId, exportMaxRows)) == 0) {
            // The rows are there but the content is not: name the reason in
            // the file itself, because an administrator opening it later will
            // not remember which keys were consented at export time.
            note = fullLoggingEnabled
                ? "No request with full logging in this window: request and response content is empty in every row of this export."
                : "Full logging is not activated for this team: request and response content was never stored, so it is empty in every row of this export.";
        }

        return new ExportPrep(teamId, userId, teamName, days, since.toInstant(), now, out,
                              totalInWindow, Math.min(totalInWindow, exportMaxRows), truncated,
                              fullLoggingEnabled, note);
    }

    /**
     * The file itself, written row by row into the response.
     *
     * Rows are fetched in chunks and written as they arrive, so the service
     * holds one chunk of the window in memory rather than the capped slice —
     * a slice of consented rows is a download, not a data structure. The
     * order and the cap are the prep's: newest first, the newest
     * {@code exportMaxRows} rows of the window.
     */
    public void writeExportFile(ExportPrep prep, OutputStream out) throws IOException {
        Timestamp since = Timestamp.from(prep.since());
        Timestamp end = Timestamp.from(prep.now());

        if (prep.format() == ExportFormat.CSV) {
            writeCsv(prep, since, end, out);
        } else {
            writeJson(prep, since, end, out);
        }
    }

    private void writeJson(ExportPrep prep, Timestamp since, Timestamp end, OutputStream out) throws IOException {
        try (JsonGenerator gen = objectMapper.getFactory().createGenerator(out)) {
            gen.setCodec(objectMapper);
            gen.writeStartObject();
            writeJsonMeta(gen, prep);
            gen.writeArrayFieldStart("traces");
            streamRows(prep, since, end, row -> {
                List<Object> values = traceValues(row);
                gen.writeStartObject();
                for (int i = 0; i < TRACE_COLUMNS.length; i++) {
                    gen.writeFieldName(TRACE_COLUMNS[i]);
                    Object value = values.get(i);
                    if (value == null) {
                        gen.writeNull();
                    } else {
                        gen.writeObject(value);
                    }
                }
                gen.writeEndObject();
            });
            gen.writeEndArray();
            gen.writeEndObject();
            gen.flush();
        }
    }

    private void writeJsonMeta(JsonGenerator gen, ExportPrep prep) throws IOException {
        gen.writeNumberField("team_id", prep.teamId());
        gen.writeStringField("team_name", prep.teamName());
        gen.writeNumberField("days", prep.days());
        gen.writeStringField("since", prep.since().toString());
        gen.writeNumberField("count", prep.count());
        gen.writeBooleanField("full_logging_enabled", prep.fullLoggingEnabled());
        if (prep.note() != null) {
            gen.writeStringField("note", prep.note());
        }
        gen.writeBooleanField("truncated", prep.truncated());
        gen.writeNumberField("total_in_window", prep.totalInWindow());
    }

    private void writeCsv(ExportPrep prep, Timestamp since, Timestamp end, OutputStream out) throws IOException {
        Writer writer = new OutputStreamWriter(out, StandardCharsets.UTF_8);
        writer.write(String.join(",", TRACE_COLUMNS));
        writer.write('\n');
        streamRows(prep, since, end, row -> {
            List<Object> values = traceValues(row);
            StringBuilder line = new StringBuilder();
            for (int i = 0; i < TRACE_COLUMNS.length; i++) {
                if (i > 0) {
                    line.append(',');
                }
                line.append(csvCell(values.get(i)));
            }
            writer.write(line.toString());
            writer.write('\n');
        });
        writer.flush();
    }

    /**
     * The shared walk of the export: chunks of rows, newest first, from the
     * start of the window down to the cap or the end of it. The row consumer
     * writes one row; the walk is what knows when to stop.
     */
    private void streamRows(ExportPrep prep, Timestamp since, Timestamp end, RowWriter rowWriter) throws IOException {
        long written = 0;
        Timestamp cursorTs = null;
        Integer cursorId = null;
        while (written < exportMaxRows) {
            List<LogExportProjection> chunk = logEntryRepository.findTracesForExport(
                prep.teamId(), since, end, prep.userId(), cursorTs, cursorId, EXPORT_CHUNK_SIZE);
            if (chunk.isEmpty()) {
                break;
            }
            for (LogExportProjection row : chunk) {
                if (written >= exportMaxRows) {
                    break;
                }
                rowWriter.write(row);
                written++;
                cursorTs = Timestamp.from(row.getTimestampRequest());
                cursorId = row.getId();
            }
            if (chunk.size() < EXPORT_CHUNK_SIZE) {
                break;
            }
        }
    }

    @FunctionalInterface
    private interface RowWriter {
        void write(LogExportProjection row) throws IOException;
    }

    /**
     * One row of the file, in the order of {@link #TRACE_COLUMNS}. Rows carry
     * nulls legitimately — a pending row has no response timestamp, a
     * billing-only row no payloads — so the list must tolerate them.
     */
    private List<Object> traceValues(LogExportProjection p) {
        return Arrays.asList(
            p.getRequestId(),
            ts(p.getTimestampRequest()),
            ts(p.getTimestampForwarding()),
            ts(p.getTimestampResponse()),
            ts(p.getTimeAtFirstToken()),
            p.getPrivacyLevel(),
            p.getModelName(),
            p.getProviderType(),
            p.getEnvironment(),
            p.getApiKeyId(),
            p.getKeyName(),
            p.getUsername(),
            p.getFullName(),
            p.getTeamName(),
            p.getClientIp(),
            p.getResultStatus() != null ? p.getResultStatus() : "pending",
            p.getErrorMessage(),
            p.getPriority(),
            p.getInitialPriority(),
            p.getPriorityWhenScheduled(),
            p.getQueueDepthAtEnqueue(),
            p.getQueueDepthAtSchedule(),
            p.getQueueDepthAtArrival(),
            p.getTimeoutS(),
            p.getUtilizationAtArrival(),
            p.getQueueWaitMs(),
            p.getWasColdStart(),
            p.getLoadDurationMs(),
            p.getAvailableVramMb(),
            p.getPromptTokens(),
            p.getCompletionTokens(),
            p.getTotalTokens(),
            p.getCostMicroCents(),
            json(p.getClassificationStatistics()),
            json(p.getInputPayload()),
            stripAuthorizationHeader(json(p.getHeaders())),
            json(p.getResponsePayload())
        );
    }

    /**
     * The headers were stored the way the request carried them — which means
     * the authorization header holds a working API key, in the clear. The
     * export is the administrator's trace of the team's traffic, not a
     * credential dump: a team owner reading this file must not be able to
     * impersonate any of their members, so the key comes out on the way.
     * The remaining headers (content-type, user-agent, …) stay.
     */
    private Object stripAuthorizationHeader(Object headers) {
        if (!(headers instanceof Map<?, ?> stored)) return headers;
        Map<String, Object> redacted = new LinkedHashMap<>();
        stored.forEach((name, value) -> {
            if (!"authorization".equalsIgnoreCase(String.valueOf(name))) {
                redacted.put(String.valueOf(name), value);
            }
        });
        return redacted;
    }

    /**
     * Back to structured data for the download. The database returns JSONB as
     * text, and a trace whose payload is a string that merely contains JSON
     * is one layer harder to read than it should be. A column that is NULL
     * stays NULL: a billing-only request stored no content at all, and a
     * FULL request whose response was never stored must read as absent
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

    /**
     * One CSV cell. Structured fields go out as compact JSON so a trace stays
     * one row; quoting follows the same rules as before this export moved
     * server-side — escape what breaks a table, because a payload is one
     * comma away from breaking it.
     */
    private String csvCell(Object value) {
        if (value == null) return "";
        String text;
        if (value instanceof String s) {
            text = s;
        } else {
            try {
                text = objectMapper.writeValueAsString(value);
            } catch (Exception e) {
                // The value came off a stored JSONB column, so this cannot
                // actually fail; if the column stops being what the schema
                // says, keep the data rather than dropping the row.
                text = String.valueOf(value);
            }
        }
        return (text.contains(",") || text.contains("\"") || text.contains("\n") || text.contains("\r"))
            ? "\"" + text.replace("\"", "\"\"") + "\""
            : text;
    }

    /** Whether any active key of the team is opted into FULL logging — the
     *  only switch under which the orchestrator stores request and response
     *  content at all.
     */
    private boolean hasFullLoggingKey(int teamId) {
        return apiKeyRepository.existsByTeamIdAndLogAndIsActive(teamId, LogLevel.FULL, true);
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

    private static long valueOrDefault(Long value) {
        return value != null ? value : 0L;
    }

    private static int clampDays(Integer requested) {
        if (requested == null) return DEFAULT_DAYS;
        return Math.max(1, Math.min(MAX_DAYS, requested));
    }

    private static String ts(Instant t) {
        return t != null ? t.toString() : null;
    }

    /** The period tier of one (team, window): what the TTL cache holds. */
    private record PeriodAggregates(List<Map<String, Object>> keys,
                                    List<Map<String, Object>> requesters,
                                    List<Map<String, Object>> mostAsked) {}

    /** A cache entry and when it was loaded, the TTL measured from here. */
    private record CacheEntry<T>(T value, long loadedAtMs) {}
}
