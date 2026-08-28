package de.tum.cit.aet.logos.logoswebservice.websocket;

import java.io.IOException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.operations.service.EnqueueEventService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogStatsService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.VramService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorLiveStreamClient;
import jakarta.annotation.PreDestroy;

@Component
public class StatsV2WebSocketHandler extends TextWebSocketHandler {

    private static final Logger log = LoggerFactory.getLogger(StatsV2WebSocketHandler.class);
    private static final int DEFAULT_TARGET_BUCKETS = 120;
    private static final int DEFAULT_WINDOW_DAYS = 30;
    // The live push sends the newest page of the feed. Same size the unscoped
    // convenience overload used, kept explicit now that the scoped call spells
    // out every argument.
    private static final int LATEST_REQUESTS_PUSH_SIZE = RequestLogService.LATEST_REQUESTS_PAGE_SIZE;


    private static class SessionState {
        volatile boolean initialized = false;
        volatile String logosKey = "";

        volatile String vramDay = null;
        volatile int vramCursor = 0;

        // The user-selected window. The live delta slide advances only the end
        // to "now"; the start stays anchored where the preset put it.
        volatile String timelineStart;
        volatile String timelineEnd;
        volatile int targetBuckets = DEFAULT_TARGET_BUCKETS;
        volatile int bucketSeconds = 60;
        volatile boolean timelineLive = true;
        volatile boolean deltaEnabled = true;
        volatile String cursorTs = null;
        volatile String cursorId = "";

        // Who the page is looking at. Null means the whole platform, which is
        // where every session starts. Applies to everything derived from
        // requests — aggregates, the volume chart's events, the request feed —
        // and to nothing else: VRAM, lanes and GPUs are properties of the
        // hardware and belong to no team, so narrowing them would be meaningless
        // rather than merely useless.
        volatile Integer scopeUserId = null;
        volatile Integer scopeTeamId = null;

        volatile String prevReqSig = "";
        volatile String prevVramMetaSig = "";

        // Traffic moved since the last aggregate push, so the totals the
        // statistics page shows are out of date. Recomputing them is a scan of
        // the whole range, so it is driven by this flag rather than by the clock:
        // an idle session costs nothing.
        volatile boolean statsDirty = false;

        void initDefaultTimeline() {
            ZonedDateTime now = ZonedDateTime.now(ZoneOffset.UTC);
            timelineEnd = now.toInstant().toString();
            timelineStart = now.minusDays(DEFAULT_WINDOW_DAYS).toInstant().toString();
            cursorTs = timelineEnd;
            cursorId = "";
            timelineLive = true;
        }

        boolean setTimeline(String start, String end, int buckets) {
            try {
                ZonedDateTime s = ZonedDateTime.parse(start.endsWith("Z") ? start : start + "Z");
                ZonedDateTime e = ZonedDateTime.parse(end.endsWith("Z") ? end : end + "Z");
                if (s.isAfter(e)) return false;
                ZonedDateTime now = ZonedDateTime.now(ZoneOffset.UTC);
                if (e.isAfter(now)) e = now;
                timelineStart = s.toInstant().toString();
                timelineEnd = e.toInstant().toString();
                targetBuckets = Math.max(1, buckets);
                timelineLive = now.toEpochSecond() - e.toEpochSecond() <= 120;
                cursorTs = timelineEnd;
                cursorId = "";
                return true;
            } catch (Exception ex) { return false; }
        }
    }

    private final VramService vramService;
    private final RequestLogService requestLogService;
    private final RequestLogStatsService statsService;
    private final EnqueueEventService enqueueService;
    private final OrchestratorLiveStreamClient liveStreamClient;
    private final ObjectMapper objectMapper;

    private final Map<String, WebSocketSession> sessions = new ConcurrentHashMap<>();
    private final Map<String, SessionState> states = new ConcurrentHashMap<>();
    private final ScheduledExecutorService scheduler;

    public StatsV2WebSocketHandler(VramService vramService,
                                   RequestLogService requestLogService,
                                   RequestLogStatsService statsService,
                                   EnqueueEventService enqueueService,
                                   OrchestratorLiveStreamClient liveStreamClient,
                                   ObjectMapper objectMapper) {
        this.vramService = vramService;
        this.requestLogService = requestLogService;
        this.statsService = statsService;
        this.enqueueService = enqueueService;
        this.liveStreamClient = liveStreamClient;
        this.objectMapper = objectMapper;
        this.scheduler = Executors.newSingleThreadScheduledExecutor();
        this.scheduler.scheduleAtFixedRate(this::tick, 1, 1, TimeUnit.SECONDS);
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        sessions.put(session.getId(), session);
        SessionState state = new SessionState();
        Object key = session.getAttributes().get("logosKey");
        state.logosKey = key instanceof String s ? s : "";
        states.put(session.getId(), state);
        log.debug("[ws/stats/v2] connected ({} total)", sessions.size());
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        sessions.remove(session.getId());
        states.remove(session.getId());
        log.debug("[ws/stats/v2] disconnected ({} remaining)", sessions.size());
    }

    @Override
    @SuppressWarnings("unchecked")
    protected void handleTextMessage(WebSocketSession session, TextMessage message) {
        SessionState state = states.get(session.getId());
        if (state == null) return;

        Map<String, Object> msg;
        try { msg = objectMapper.readValue(message.getPayload(), Map.class); }
        catch (Exception e) { return; }

        String action = (String) msg.get("action");
        if (action == null) return;

        switch (action) {
            case "init" -> handleInit(session, state, msg);
            case "set_vram_day" -> handleSetVramDay(session, state, msg);
            case "set_timeline_range" -> handleSetTimelineRange(session, state, msg);
            case "set_scope" -> handleSetScope(session, state, msg);
            case "ping" -> send(session, Map.of("type", "pong"));
        }
    }

    @SuppressWarnings("unchecked")
    private void handleInit(WebSocketSession session, SessionState state, Map<String, Object> msg) {
        state.initialized = false;

        Object dayObj = msg.get("vram_day");
        state.vramDay = (dayObj instanceof String s && !s.isBlank()) ? s : null;
        state.vramCursor = 0;

        Object tdObj = msg.get("timeline_deltas");
        state.deltaEnabled = tdObj == null || coerceBool(tdObj, true);

        // Carried on init as well as through set_scope, so a reconnect restores
        // the filter the page is showing instead of silently widening back to
        // the whole platform under an unchanged pair of dropdowns.
        applyScope(state, msg);

        Map<String, Object> tl = msg.get("timeline") instanceof Map<?,?> m
            ? (Map<String, Object>) m : Map.of();
        String start = tl.get("start") instanceof String s ? s : null;
        String end = tl.get("end") instanceof String s ? s : null;
        int buckets = tl.get("target_buckets") instanceof Number n ? n.intValue() : DEFAULT_TARGET_BUCKETS;

        if (start == null || end == null) { state.initDefaultTimeline(); }
        else if (!state.setTimeline(start, end, buckets)) {
            send(session, Map.of("type", "timeline_init",
                                 "payload", Map.of("error", "Invalid timeline range")));
            state.initDefaultTimeline();
        }

        pushTimelineInit(session, state);
        pushVramInit(session, state);
        pushRequests(session, state, true);
        state.initialized = true;
    }

    /**
     * Narrow every request-derived push to one team and/or one requester.
     *
     * Both ids are cleared by sending null (or omitting them), which is the
     * unfiltered view the session starts in. The reply is a full re-push rather
     * than a delta: the client's event list and aggregates describe the old
     * scope and there is no delta that turns them into the new one.
     */
    private void handleSetScope(WebSocketSession session, SessionState state, Map<String, Object> msg) {
        applyScope(state, msg);
        // The cursor points into the old scope's event stream; deltas resumed
        // from it would skip everything the new scope should have seen.
        state.cursorTs = state.timelineEnd;
        state.cursorId = "";
        pushTimelineInit(session, state);
        pushRequests(session, state, true);
    }

    private static void applyScope(SessionState state, Map<String, Object> msg) {
        state.scopeUserId = msg.get("user_id") instanceof Number n ? n.intValue() : null;
        state.scopeTeamId = msg.get("team_id") instanceof Number n ? n.intValue() : null;
    }

    private void handleSetVramDay(WebSocketSession session, SessionState state, Map<String, Object> msg) {
        Object dayObj = msg.get("day");
        if (dayObj instanceof String s && !s.isBlank()) {
            state.vramDay = s;
            state.vramCursor = 0;
            pushVramInit(session, state);
        }
    }

    @SuppressWarnings("unchecked")
    private void handleSetTimelineRange(WebSocketSession session, SessionState state, Map<String, Object> msg) {
        String start = msg.get("start") instanceof String s ? s : null;
        String end = msg.get("end") instanceof String s ? s : null;
        int    buckets = msg.get("target_buckets") instanceof Number n ? n.intValue() : DEFAULT_TARGET_BUCKETS;
        if (start == null || end == null || !state.setTimeline(start, end, buckets)) {
            send(session, Map.of("type", "timeline_init",
                                 "payload", Map.of("error", "Invalid timeline range")));
        } else {
            pushTimelineInit(session, state);
            pushRequests(session, state, true);
        }
    }

    private int globalTick = 0;

    private void tick() {
        int t = globalTick++;
        for (Map.Entry<String, WebSocketSession> entry : sessions.entrySet()) {
            WebSocketSession session = entry.getValue();
            SessionState state = states.get(entry.getKey());
            if (state == null || !state.initialized || !session.isOpen()) continue;

            try {
                if (t % 2 == 0) {
                    pushRequests(session, state, false);
                    if (state.deltaEnabled && state.timelineLive) {
                        pushTimelineDelta(session, state);
                    }
                }
                if (t % 5 == 0) {
                    pushVramDelta(session, state);
                }
                // Aggregates are the expensive push (findTotals alone scans the
                // range twice more for tokens and cost), so they go out at a
                // tenth of the request cadence and only when the request feed
                // actually reported a change. Without this the page's counters
                // never moved after load: stats only ever came with
                // timeline_init, i.e. on connect and on a range change.
                if (t % 10 == 0 && state.statsDirty) {
                    state.statsDirty = false;
                    pushStats(session, state);
                }
            } catch (Exception e) {
                log.warn("[ws/stats/v2] tick error for session {}: {}", entry.getKey(), e.getMessage());
            }
        }
    }

    private void pushVramInit(WebSocketSession session, SessionState state) {
        try {
            String day = state.vramDay != null ? state.vramDay : LocalDate.now(ZoneOffset.UTC).toString();
            Map<String, Object> payload = vramService.getVramStats(day, 0);
            Object sid = payload.get("last_snapshot_id");
            state.vramCursor = sid instanceof Number n ? n.intValue() : 0;
            state.prevVramMetaSig = vramMetaSig(payload);
            send(session, Map.of("type", "vram_init", "payload", payload));
        } catch (Exception e) {
            send(session, Map.of("type", "vram_init", "payload", Map.of("error", "Failed to load VRAM data")));
        }
    }

    private void pushVramDelta(WebSocketSession session, SessionState state) {
        try {
            String day = state.vramDay != null ? state.vramDay : LocalDate.now(ZoneOffset.UTC).toString();
            Map<String, Object> payload = vramService.getVramStats(day, state.vramCursor);
            Object sid = payload.get("last_snapshot_id");
            int nextCursor = sid instanceof Number n ? n.intValue() : state.vramCursor;
            // Providers are always present (connection metadata is attached
            // even without new snapshots), so deltas are pushed only when new
            // samples arrived, the cursor moved, or a provider's connection
            // state flipped (e.g. a worker went offline — exactly the moment
            // no new snapshots arrive anymore).
            boolean hasNewSamples = hasSamples(payload);
            String metaSig = vramMetaSig(payload);
            boolean metaChanged = !metaSig.equals(state.prevVramMetaSig);
            if (hasNewSamples || nextCursor != state.vramCursor || metaChanged) {
                state.vramCursor = nextCursor;
                state.prevVramMetaSig = metaSig;
                send(session, Map.of("type", "vram_delta", "payload", payload));
            }
        } catch (Exception e) {
            log.warn("[ws/stats/v2] vram_delta error: {}", e.getMessage());
        }
    }

    private static boolean hasSamples(Map<String, Object> payload) {
        if (!(payload.get("providers") instanceof java.util.List<?> providers)) return false;
        for (Object p : providers) {
            if (p instanceof Map<?, ?> provider
                    && provider.get("data") instanceof java.util.List<?> data
                    && !data.isEmpty()) {
                return true;
            }
        }
        return false;
    }

    private static String vramMetaSig(Map<String, Object> payload) {
        if (!(payload.get("providers") instanceof java.util.List<?> providers)) return "";
        StringBuilder sb = new StringBuilder();
        for (Object p : providers) {
            if (!(p instanceof Map<?, ?> provider)) continue;
            sb.append(provider.get("provider_id")).append(':')
              .append(provider.get("connection_state")).append(':')
              .append(provider.get("calibrating")).append(',');
        }
        return sb.toString();
    }

    private void pushTimelineInit(WebSocketSession session, SessionState state) {
        try {
            Map<String, Object> stats = statsService.getRequestLogStats(
                state.timelineStart, state.timelineEnd, state.targetBuckets,
                state.scopeUserId, state.scopeTeamId);
            state.bucketSeconds = stats.get("bucketSeconds") instanceof Number n ? n.intValue() : 60;

            Map<String, Object> events = enqueueService.getInRange(
                state.timelineStart, state.timelineEnd, 200_000,
                state.scopeUserId, state.scopeTeamId);

            Map<String, Object> payload = new LinkedHashMap<>(stats);
            payload.put("cursor",  Map.of("enqueue_ts", state.cursorTs != null ? state.cursorTs : "",
                                          "request_id", state.cursorId));
            payload.put("events", events.get("events"));
            send(session, Map.of("type", "timeline_init", "payload", payload));
        } catch (Exception e) {
            send(session, Map.of("type", "timeline_init", "payload", Map.of("error", "Failed to load timeline data")));
        }
    }

    /**
     * Re-send the aggregates for the session's range.
     *
     * Deliberately not {@link #pushTimelineInit}: that one also ships every
     * enqueue event in the range (up to 200k rows), which is fine once on
     * connect and far too much to repeat while the page is open. The client
     * keeps its event list current from the deltas instead.
     */
    private void pushStats(WebSocketSession session, SessionState state) {
        try {
            // A live selection keeps growing, so it has to be queried up to now,
            // the same way pushRequests and pushTimelineDelta do it. Only the end
            // moves; the start stays where the preset put it.
            if (state.timelineLive) state.timelineEnd = Instant.now().toString();

            Map<String, Object> stats = statsService.getRequestLogStats(
                state.timelineStart, state.timelineEnd, state.targetBuckets,
                state.scopeUserId, state.scopeTeamId);
            state.bucketSeconds = stats.get("bucketSeconds") instanceof Number n
                ? n.intValue() : state.bucketSeconds;
            send(session, Map.of("type", "stats", "payload", stats));
        } catch (Exception e) {
            log.warn("[ws/stats/v2] stats push error: {}", e.getMessage());
        }
    }

    private void pushTimelineDelta(WebSocketSession session, SessionState state) {
        try {
            String untilIso = Instant.now().toString();
            Map<String, Object> result = enqueueService.getDeltas(
                state.cursorTs, state.cursorId, untilIso, 5000,
                state.scopeUserId, state.scopeTeamId);

            @SuppressWarnings("unchecked")
            var events = (java.util.List<?>) result.get("events");
            if (events == null || events.isEmpty()) return;

            @SuppressWarnings("unchecked")
            Map<String, Object> cursor = (Map<String, Object>) result.get("cursor");
            String newTs = (String) cursor.get("enqueue_ts");
            String newId = (String) cursor.get("request_id");
            if (newTs != null && !newTs.isBlank()) { state.cursorTs = newTs; state.cursorId = newId; }

            // Only the end moves. Re-anchoring the start to now-windowSeconds
            // would turn every calendar-anchored preset into a rolling window:
            // picking "Today" at 00:20 gives a 20-minute span, so an hour later
            // the view would cover 01:00–01:20 instead of the whole day.
            state.timelineEnd = untilIso;

            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("events", events);
            payload.put("cursor", Map.of("enqueue_ts", state.cursorTs != null ? state.cursorTs : "",
                                         "request_id", state.cursorId));
            payload.put("bucketSeconds", state.bucketSeconds);
            payload.put("range", Map.of("start", state.timelineStart, "end", state.timelineEnd));
            send(session, Map.of("type", "timeline_delta", "payload", payload));
        } catch (Exception e) {
            log.warn("[ws/stats/v2] timeline_delta error: {}", e.getMessage());
        }
    }

    private void pushRequests(WebSocketSession session, SessionState state, boolean force) {
        try {
            // A live selection ("last 30 days", "today", …) keeps growing while
            // the page is open, so the request list has to query up to *now*.
            // state.timelineEnd is only advanced by pushTimelineDelta, which the
            // statistics page disables (timelineDeltas: false) — reading it here
            // would pin the list to the instant the range was set and no request
            // enqueued after page load would ever show up.
            String end = state.timelineLive ? Instant.now().toString() : state.timelineEnd;
            Map<String, Object> payload = requestLogService.getLatestRequests(
                state.timelineStart, end, state.scopeUserId, state.scopeTeamId,
                null, null, LATEST_REQUESTS_PUSH_SIZE, false);
            mergeLiveStreams(payload);
            String sig = requestsSig(payload);
            if (!sig.equals(state.prevReqSig)) {
                // A request arrived, finished, or grew its usage — whatever the
                // aggregates summarise has moved with it.
                state.statsDirty = true;
            }
            if (force || !sig.equals(state.prevReqSig)) {
                state.prevReqSig = sig;
                send(session, Map.of("type", "requests", "payload", payload));
            }
        } catch (Exception e) {
            log.warn("[ws/stats/v2] requests push error: {}", e.getMessage());
        }
    }

    /**
     * Fill in the token counts of the requests that are still streaming.
     *
     * Usage is written to the database once, when the request completes. Until
     * then its row carries nothing, so a generation that runs for a minute sat
     * in the feed as a blank line and then produced all its numbers at once.
     * The orchestrator is the only process that sees the chunks go past, so the
     * in-flight figures come from there.
     *
     * Only rows the database has nothing for are touched: a completed request's
     * settled usage always wins over the live estimate behind it.
     */
    @SuppressWarnings("unchecked")
    private void mergeLiveStreams(Map<String, Object> payload) {
        var requests = (java.util.List<Map<String, Object>>) payload.get("requests");
        if (requests == null || requests.isEmpty()) return;
        // Only ask when something on this page could still be running. A feed of
        // finished requests — the common case for any range but "now" — must not
        // cost a call per push.
        boolean anyUnfinished = requests.stream()
            .anyMatch(r -> r.get("request_complete_ts") == null || r.get("total_tokens") == null);
        if (!anyUnfinished) return;

        Map<String, OrchestratorLiveStreamClient.LiveStream> live = liveStreamClient.getLiveStreams();
        if (live.isEmpty()) return;

        for (Map<String, Object> request : requests) {
            if (!(request.get("request_id") instanceof String requestId)) continue;
            var stream = live.get(requestId);
            if (stream == null) continue;
            if (request.get("total_tokens") != null) continue;  // already settled
            request.put("prompt_tokens", stream.promptTokens());
            request.put("completion_tokens", stream.completionTokens());
            request.put("total_tokens", stream.promptTokens() + stream.completionTokens());
            request.put("tokens_per_second", stream.tokensPerSecond());
            // Says outright that these are the in-flight figures, so the page can
            // present them as moving rather than final.
            request.put("streaming", true);
        }
    }

    // Content-only signature: the live window slide advances the range on
    // every delta, which must not force a push — user-driven range changes
    // are already pushed explicitly (force=true) in handleSetTimelineRange.
    //
    // Every field the row renders has to be in here: the push is skipped
    // whenever the signature repeats, so a change to a field that is left out
    // never reaches the page. The provider in particular moves after the first
    // push — the row carries the deployment the request was made for from
    // enqueue time, and the provider that actually serves it is only written
    // once the request is scheduled (and can be re-resolved once the execution
    // context lands). Without it in the signature, a re-routed request kept
    // showing its queued-time provider while the badge next to it moved on.
    @SuppressWarnings("unchecked")
    static String requestsSig(Map<String, Object> payload) {
        var reqs = (java.util.List<Map<String, Object>>) payload.getOrDefault("requests", java.util.List.of());
        StringBuilder sb = new StringBuilder();
        for (var r : reqs) {
            sb.append(r.getOrDefault("request_id", "")).append(':')
              .append(r.getOrDefault("status", "")).append(':')
              .append(r.getOrDefault("provider_name", "")).append(':')
              // Rendered as the Cloud/Local badge, so the same rule as the
              // name applies: a change to it must not be deduplicated away.
              .append(r.getOrDefault("is_cloud", "")).append(':')
              .append(r.getOrDefault("scheduled_ts", "")).append(':')
              .append(r.getOrDefault("request_complete_ts", "")).append(':')
              // Usage and cost grow while a request streams, without any of the
              // fields above changing — leaving them out of the signature pins
              // the token and cost line of a running request to its first push.
              .append(r.getOrDefault("prompt_tokens", "")).append(':')
              .append(r.getOrDefault("completion_tokens", "")).append(':')
              .append(r.getOrDefault("total_tokens", "")).append(':')
              .append(r.getOrDefault("cost_microcents", "")).append(',');
        }
        return sb.toString();
    }

    private void send(WebSocketSession session, Object payload) {
        try {
            String json = objectMapper.writeValueAsString(payload);
            synchronized (session) {
                if (session.isOpen()) session.sendMessage(new TextMessage(json));
            }
        } catch (IOException e) {
            sessions.remove(session.getId());
            states.remove(session.getId());
        } catch (Exception e) {
            log.warn("[ws/stats/v2] send error: {}", e.getMessage());
        }
    }

    private static boolean coerceBool(Object v, boolean def) {
        if (v instanceof Boolean b) return b;
        if (v instanceof Number n)  return n.intValue() != 0;
        if (v instanceof String s)  return switch (s.strip().toLowerCase()) {
            case "true","1","yes","on" -> true;
            case "false","0","no","off" -> false;
            default -> def;
        };
        return def;
    }

    @PreDestroy
    public void shutdown() { scheduler.shutdownNow(); }
}
