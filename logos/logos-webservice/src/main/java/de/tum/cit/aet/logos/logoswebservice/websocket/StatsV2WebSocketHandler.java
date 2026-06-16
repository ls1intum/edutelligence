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
import jakarta.annotation.PreDestroy;

@Component
public class StatsV2WebSocketHandler extends TextWebSocketHandler {

    private static final Logger log = LoggerFactory.getLogger(StatsV2WebSocketHandler.class);
    private static final int DEFAULT_TARGET_BUCKETS = 120;
    private static final int DEFAULT_WINDOW_DAYS = 30;


    private static class SessionState {
        volatile boolean initialized = false;
        volatile String logosKey = "";

        volatile String vramDay = null;
        volatile int vramCursor = 0;

        volatile String timelineStart;
        volatile String timelineEnd;
        volatile int targetBuckets = DEFAULT_TARGET_BUCKETS;
        volatile int bucketSeconds = 60;
        volatile boolean timelineLive = true;
        volatile boolean deltaEnabled = true;
        volatile String cursorTs = null;
        volatile String cursorId = "";

        volatile String prevReqSig = "";
        volatile String prevVramMetaSig = "";

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
    private final ObjectMapper objectMapper;

    private final Map<String, WebSocketSession> sessions = new ConcurrentHashMap<>();
    private final Map<String, SessionState> states = new ConcurrentHashMap<>();
    private final ScheduledExecutorService scheduler;

    public StatsV2WebSocketHandler(VramService vramService,
                                   RequestLogService requestLogService,
                                   RequestLogStatsService statsService,
                                   EnqueueEventService enqueueService,
                                   ObjectMapper objectMapper) {
        this.vramService = vramService;
        this.requestLogService = requestLogService;
        this.statsService = statsService;
        this.enqueueService = enqueueService;
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
              .append(provider.get("connection_state")).append(',');
        }
        return sb.toString();
    }

    private void pushTimelineInit(WebSocketSession session, SessionState state) {
        try {
            Map<String, Object> stats = statsService.getRequestLogStats(
                state.timelineStart, state.timelineEnd, state.targetBuckets);
            state.bucketSeconds = stats.get("bucketSeconds") instanceof Number n ? n.intValue() : 60;

            Map<String, Object> events = enqueueService.getInRange(
                state.timelineStart, state.timelineEnd, 200_000);

            Map<String, Object> payload = new LinkedHashMap<>(stats);
            payload.put("cursor",  Map.of("enqueue_ts", state.cursorTs != null ? state.cursorTs : "",
                                          "request_id", state.cursorId));
            payload.put("events", events.get("events"));
            send(session, Map.of("type", "timeline_init", "payload", payload));
        } catch (Exception e) {
            send(session, Map.of("type", "timeline_init", "payload", Map.of("error", "Failed to load timeline data")));
        }
    }

    private void pushTimelineDelta(WebSocketSession session, SessionState state) {
        try {
            String untilIso = Instant.now().toString();
            Map<String, Object> result = enqueueService.getDeltas(
                state.cursorTs, state.cursorId, untilIso, 5000);

            @SuppressWarnings("unchecked")
            var events = (java.util.List<?>) result.get("events");
            if (events == null || events.isEmpty()) return;

            @SuppressWarnings("unchecked")
            Map<String, Object> cursor = (Map<String, Object>) result.get("cursor");
            String newTs = (String) cursor.get("enqueue_ts");
            String newId = (String) cursor.get("request_id");
            if (newTs != null && !newTs.isBlank()) { state.cursorTs = newTs; state.cursorId = newId; }

            ZonedDateTime now = ZonedDateTime.now(ZoneOffset.UTC);
            state.timelineEnd   = untilIso;
            state.timelineStart = now.minusSeconds((long)(DEFAULT_WINDOW_DAYS * 86400L)).toInstant().toString();

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
            Map<String, Object> payload = requestLogService.getLatestRequests();
            String sig = requestsSig(payload);
            if (force || !sig.equals(state.prevReqSig)) {
                state.prevReqSig = sig;
                send(session, Map.of("type", "requests", "payload", payload));
            }
        } catch (Exception e) {
            log.warn("[ws/stats/v2] requests push error: {}", e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    private String requestsSig(Map<String, Object> payload) {
        var reqs = (java.util.List<Map<String, Object>>) payload.getOrDefault("requests", java.util.List.of());
        StringBuilder sb = new StringBuilder();
        for (var r : reqs) {
            sb.append(r.getOrDefault("request_id", "")).append(':')
              .append(r.getOrDefault("status", "")).append(':')
              .append(r.getOrDefault("scheduled_ts", "")).append(':')
              .append(r.getOrDefault("request_complete_ts", "")).append(',');
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
