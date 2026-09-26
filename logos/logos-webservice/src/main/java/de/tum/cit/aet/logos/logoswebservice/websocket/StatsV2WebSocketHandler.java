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
import java.util.concurrent.atomic.AtomicReference;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import com.fasterxml.jackson.databind.ObjectMapper;

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


    // The vram window a session is looking at: the selected day (null =
    // today), the cursor into it, the provider connection-state baseline, and
    // whether the window's init — the full-day payload that establishes the
    // viewer's baseline — has gone out. One immutable reference so a
    // transition (init, set_vram_day) is a single atomic swap and the tick
    // thread's snapshot is a single atomic read — transition and snapshot can
    // never disagree. Separate volatile fields (however ordered) cannot
    // guarantee that: the writer can always pause between the generation bump
    // and the day write, letting the tick capture a fresh generation with the
    // stale day.
    record VramWindow(String day, int cursor, String metaSig, boolean baselineSent) {}

    // Package-private, with its fields, so the unit test can pin the
    // isCurrentVramWindow predicate on a real state instance.
    static class SessionState {
        volatile boolean initialized = false;
        volatile String logosKey = "";

        // The current vram window; swapped atomically on every change. The
        // reference identity is the generation: any earlier snapshot is stale
        // the moment it is swapped out, whatever the writer paused on.
        final AtomicReference<VramWindow> vramWindow = new AtomicReference<>(new VramWindow(null, 0, "", false));

        // The one ordering mechanism between window transitions and
        // publication. The tick's delta (capture to send) and every
        // transition (the swap plus its init push) run under it, so a push
        // for a superseded window always reaches the viewer before the newer
        // window's init: the compareAndSet guards the state, this guard
        // guards the order the messages arrive in.
        final Object vramLock = new Object();

        // The user-selected window. The live delta slide advances only the end
        // to "now"; the start stays anchored where the preset put it.
        volatile String timelineStart;
        volatile String timelineEnd;
        volatile int targetBuckets = DEFAULT_TARGET_BUCKETS;
        volatile int bucketSeconds = 60;
        volatile boolean timelineLive = true;

        // Who the page is looking at. Null means the whole platform, which is
        // where every session starts. Applies to everything derived from
        // requests — aggregates, the volume chart's events, the request feed —
        // and to nothing else: VRAM, lanes and GPUs are properties of the
        // hardware and belong to no team, so narrowing them would be meaningless
        // rather than merely useless.
        volatile Integer scopeUserId = null;
        volatile Integer scopeTeamId = null;
        volatile Integer scopeProviderId = null;
        volatile boolean scopeErrorsOnly = false;

        // One lifecycle bucket the request feed is narrowed to (queued, running,
        // error, finished); null shows all states. Deliberately not part of the
        // scope above: the scope is who the whole page looks at, and it narrows
        // the aggregates and the volume chart too. A state filter only makes
        // sense for the request feed, so it must not drag the KPI cards and
        // charts into a slice of the log they are meant to summarise in full.
        volatile String feedStatus = null;

        // Which half of the statistics page this session is looking at.
        // "local-providers" → VRAM / lanes / GPUs only; "requests" → aggregates
        // and the request feed only. Null means both (legacy clients that never
        // declare an interest, and unit tests that init without one). The page
        // can show only one tab at a time, so pushing the idle tab's channel is
        // wasted work on both sides of the socket.
        volatile String interest = null;

        volatile String prevReqSig = "";

        boolean wantsLocalProviders() {
            return interest == null || "local-providers".equals(interest);
        }

        boolean wantsRequests() {
            return interest == null || "requests".equals(interest);
        }
        // The request ids of the last pushed page — the row set, values
        // excluded. Token counts grow without this moving, and the feed's
        // own count cannot change with them, so a changed row set is the
        // only moment the count is re-queried.
        volatile String prevFeedIdsSig = "";
        // The last scope-wide movement probe (see scopeMovementSig). Reset to
        // empty wherever the aggregates are re-pushed in full (init, scope
        // or range change), so the first probe under a fresh window is just
        // a baseline and does not trigger a redundant stats push on top of
        // the one timeline_init already sent.
        volatile String prevScopeSig = "";

        // Traffic moved since the last aggregate push, so the totals the
        // statistics page shows are out of date. Recomputing them is a scan of
        // the whole range, so it is driven by this flag rather than by the clock:
        // an idle session costs nothing.
        volatile boolean statsDirty = false;

        void initDefaultTimeline() {
            ZonedDateTime now = ZonedDateTime.now(ZoneOffset.UTC);
            timelineEnd = now.toInstant().toString();
            timelineStart = now.minusDays(DEFAULT_WINDOW_DAYS).toInstant().toString();
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
                return true;
            } catch (Exception ex) { return false; }
        }
    }

    private final VramService vramService;
    private final RequestLogService requestLogService;
    private final RequestLogStatsService statsService;
    private final OrchestratorLiveStreamClient liveStreamClient;
    private final ObjectMapper objectMapper;

    private final Map<String, WebSocketSession> sessions = new ConcurrentHashMap<>();
    private final Map<String, SessionState> states = new ConcurrentHashMap<>();
    private final ScheduledExecutorService scheduler;

    public StatsV2WebSocketHandler(VramService vramService,
                                   RequestLogService requestLogService,
                                   RequestLogStatsService statsService,
                                   OrchestratorLiveStreamClient liveStreamClient,
                                   ObjectMapper objectMapper) {
        this.vramService = vramService;
        this.requestLogService = requestLogService;
        this.statsService = statsService;
        this.liveStreamClient = liveStreamClient;
        this.objectMapper = objectMapper;
        this.scheduler = Executors.newSingleThreadScheduledExecutor();
        this.scheduler.scheduleAtFixedRate(this::tick, 1, 1, TimeUnit.SECONDS);
        // The orchestrator pushes a fresh live snapshot as it happens; forward
        // it to the viewers without waiting for the next tick, which is what
        // makes the token numbers move in real time instead of in steps.
        liveStreamClient.setOnLiveUpdate(this::onLiveUpdate);
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
            case "set_feed_status" -> handleSetFeedStatus(session, state, msg);
            case "set_interest" -> handleSetInterest(session, state, msg);
            case "ping" -> send(session, Map.of("type", "pong"));
        }
    }

    @SuppressWarnings("unchecked")
    private void handleInit(WebSocketSession session, SessionState state, Map<String, Object> msg) {
        state.initialized = false;

        Object dayObj = msg.get("vram_day");
        String vramDay = (dayObj instanceof String s && !s.isBlank()) ? s : null;

        // Carried on init as well as through set_scope, so a reconnect restores
        // the filter the page is showing instead of silently widening back to
        // the whole platform under an unchanged pair of dropdowns.
        applyScope(state, msg);
        applyFeedStatus(state, msg);
        // Same for the active tab: a reconnect must not flood the idle channel.
        applyInterest(state, msg);

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
        // The init push below re-sends the aggregates, so the scope-wide
        // movement probe starts from a fresh baseline rather than reporting
        // the reconnect as one more move.
        state.prevScopeSig = "";

        if (state.wantsRequests()) {
            pushTimelineInit(session, state);
            pushRequests(session, state, true);
        }
        // The window swap and its init publication are one critical section
        // on the vram lock — see vramLock. Still reset the window even when
        // the viewer is on Requests so a later switch to Local Providers
        // starts from a clean baseline rather than a cursor from a previous
        // visit.
        synchronized (state.vramLock) {
            state.vramWindow.set(new VramWindow(vramDay, 0, "", false));
            if (state.wantsLocalProviders()) {
                pushVramInit(session, state);
            }
        }
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
        // The init re-push below already carries the new scope's aggregates.
        state.prevScopeSig = "";
        // Scope only shapes request-derived panels; skip the push while the
        // viewer is on Local Providers — the values are applied and will go
        // out with the next Requests interest switch.
        if (!state.wantsRequests()) return;
        pushTimelineInit(session, state);
        pushRequests(session, state, true);
    }

    private static void applyScope(SessionState state, Map<String, Object> msg) {
        state.scopeUserId = msg.get("user_id") instanceof Number n ? n.intValue() : null;
        state.scopeTeamId = msg.get("team_id") instanceof Number n ? n.intValue() : null;
        state.scopeProviderId = msg.get("provider_id") instanceof Number n ? n.intValue() : null;
        state.scopeErrorsOnly = Boolean.TRUE.equals(msg.get("errors_only"));
    }

    /**
     * The feed's state bucket, read from {@code init} and {@code set_feed_status}.
     * Absent, blank, or non-string means all states; a value naming none of
     * the buckets matches no rows. Unlike the client's normalizeFeedStatus,
     * which widens on any value outside the four buckets, an unknown
     * non-blank string is kept and fails closed here: a stale picker may
     * widen, because a filter that shows nothing reads as broken, but a
     * value sent straight to the server must not silently widen an
     * admin-only feed to the whole platform.
     */
    private static void applyFeedStatus(SessionState state, Map<String, Object> msg) {
        state.feedStatus = msg.get("status") instanceof String s && !s.isBlank() ? s : null;
    }

    /**
     * Narrow the request feed to one lifecycle bucket.
     *
     * Unlike {@link #handleSetScope} this re-pushes only the feed, not the
     * aggregates: the KPI cards and the volume chart summarise the whole scope,
     * and a state filter does not change what they describe. A forced feed push
     * is enough — no delta turns the unfiltered rows into the filtered ones.
     */
    private void handleSetFeedStatus(WebSocketSession session, SessionState state, Map<String, Object> msg) {
        applyFeedStatus(state, msg);
        if (!state.wantsRequests()) return;
        pushRequests(session, state, true);
    }

    /**
     * Which tab the page is showing. Stored and applied the same way as scope:
     * carried on init so a reconnect restores it, and sent on every switch so
     * the idle channel stops being pushed. The reply is a full init for the
     * newly enabled channel — there is no delta that turns VRAM samples into
     * request aggregates or the other way around.
     */
    private void handleSetInterest(WebSocketSession session, SessionState state, Map<String, Object> msg) {
        String previous = state.interest;
        applyInterest(state, msg);
        if (previous != null && previous.equals(state.interest)) return;

        if (state.wantsRequests()) {
            state.prevScopeSig = "";
            pushTimelineInit(session, state);
            pushRequests(session, state, true);
        }
        if (state.wantsLocalProviders()) {
            synchronized (state.vramLock) {
                // Force a fresh baseline: the cursor from a previous visit (or
                // from an init that skipped the VRAM push) would otherwise
                // only stream deltas the client has no series for.
                VramWindow current = state.vramWindow.get();
                state.vramWindow.set(new VramWindow(current.day(), 0, "", false));
                pushVramInit(session, state);
            }
        }
    }

    private static void applyInterest(SessionState state, Map<String, Object> msg) {
        Object raw = msg.get("interest");
        // Only the two tab ids are accepted. Absent on init keeps null (= both
        // channels) for legacy clients; an unknown value is ignored so a typo
        // cannot widen or clear a declared interest.
        if (raw instanceof String s && ("local-providers".equals(s) || "requests".equals(s))) {
            state.interest = s;
        }
    }

    private void handleSetVramDay(WebSocketSession session, SessionState state, Map<String, Object> msg) {
        Object dayObj = msg.get("day");
        if (dayObj instanceof String s && !s.isBlank()) {
            // One critical section on the vram lock — see vramLock.
            synchronized (state.vramLock) {
                state.vramWindow.set(new VramWindow(s, 0, "", false));
                if (state.wantsLocalProviders()) {
                    pushVramInit(session, state);
                }
            }
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
            // The init re-push below already carries the new range's aggregates.
            state.prevScopeSig = "";
            if (!state.wantsRequests()) return;
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
                if (state.wantsRequests() && t % 2 == 0) {
                    pushRequests(session, state, false);
                }
                // VRAM deltas ride every tick: a lane the worker just loaded
                // reaches the UI within one second of its status report
                // instead of waiting up to five for the next vram cadence.
                // The fetch is cursor-scoped (new snapshots only) and the
                // provider-status hop is cached for 3 s, so the per-tick cost
                // stays small; the push itself is still skipped when nothing
                // moved (no new samples, cursor, or connection state).
                if (state.wantsLocalProviders()) {
                    pushVramDelta(session, state);
                }
                // Aggregates are the expensive push (findTotals alone scans the
                // range twice more for tokens and cost), so they go out at a
                // tenth of the request cadence and only when something in
                // their scope reported a change: the request feed itself, or —
                // while a state filter narrows it to one bucket — the
                // scope-wide movement probe pushRequests keeps for exactly
                // this flag. Without this the page's counters never moved
                // after load: stats only ever came with timeline_init, i.e. on
                // connect and on a range change.
                if (state.wantsRequests() && t % 10 == 0 && state.statsDirty) {
                    state.statsDirty = false;
                    pushStats(session, state);
                }
            } catch (Exception e) {
                log.warn("[ws/stats/v2] tick error for session {}: {}", entry.getKey(), e.getMessage());
            }
        }
    }

    private void pushVramInit(WebSocketSession session, SessionState state) {
        VramWindow window = null;
        try {
            window = state.vramWindow.get();
            // A baseline already went out for this window — the websocket
            // thread's init or an earlier tick's retry established it:
            // pushing the full day again would only restate what the viewer
            // has.
            if (window.baselineSent()) return;
            String day = window.day() != null ? window.day() : LocalDate.now(ZoneOffset.UTC).toString();
            Map<String, Object> payload = vramService.getVramStats(day, 0);
            Object sid = payload.get("last_snapshot_id");
            int cursor = sid instanceof Number n ? n.intValue() : 0;
            // The payload belongs to the window it was captured for; if a
            // window change swapped the reference meanwhile, that window's
            // init is responsible for the push — the stale baseline is
            // dropped together with the stale payload.
            if (state.vramWindow.compareAndSet(window, new VramWindow(window.day(), cursor, vramMetaSig(payload), true))) {
                send(session, Map.of("type", "vram_init", "payload", payload));
            }
        } catch (Exception e) {
            log.warn("[ws/stats/v2] vram_init error: {}", e.getMessage());
            // The error belongs to the window this init was captured for. If
            // a day change swapped it out while the query was in flight, the
            // newer window's init owns the viewer's baseline now — publishing
            // this stale failure would overwrite a good day with an error.
            if (window != null && isCurrentVramWindow(state, window)) {
                send(session, Map.of("type", "vram_init", "payload", Map.of("error", "Failed to load VRAM data")));
            }
        }
    }

    private void pushVramDelta(WebSocketSession session, SessionState state) {
        // The whole capture-to-send section runs on the vram lock (see
        // vramLock): a window transition cannot land between this delta's
        // capture and its publication, so a push for a superseded window
        // always reaches the viewer before the newer window's init. The
        // compareAndSet below stays as the state-level guard.
        synchronized (state.vramLock) {
            try {
                // The snapshot is one atomic read: whatever the in-flight
                // query fetched is checked against the very reference it was
                // captured from, and written back only by compareAndSet. A
                // window change (init, set_vram_day) swaps the reference, so
                // an in-flight delta spanning the change is dropped whatever
                // it fetched — it can never send previous-day samples or
                // overwrite the new day's cursor and connection-state
                // baseline.
                VramWindow window = state.vramWindow.get();
                // A window whose init has not gone out yet is not consumable
                // by a delta: init and the first delta after a day change
                // query the same (day, cursor 0) and race for the write-back
                // — whichever loses the compareAndSet drops its push, and a
                // delta winning that race would owe the viewer a full-day
                // "init" that never comes. Instead the tick retries the owed
                // init: one transient failure of the websocket thread's init
                // must not wedge the session's vram feed behind a window no
                // push will ever touch.
                if (!window.baselineSent()) {
                    pushVramInit(session, state);
                    return;
                }
                String day = window.day() != null ? window.day() : LocalDate.now(ZoneOffset.UTC).toString();
                Map<String, Object> payload = vramService.getVramStats(day, window.cursor());
                Object sid = payload.get("last_snapshot_id");
                int nextCursor = sid instanceof Number n ? n.intValue() : window.cursor();
                // Providers are always present (connection metadata is
                // attached even without new snapshots), so deltas are pushed
                // only when new samples arrived, the cursor moved, or a
                // provider's connection state flipped (e.g. a worker went
                // offline — exactly the moment no new snapshots arrive
                // anymore).
                boolean hasNewSamples = hasSamples(payload);
                String metaSig = vramMetaSig(payload);
                boolean metaChanged = !metaSig.equals(window.metaSig());
                if (hasNewSamples || nextCursor != window.cursor() || metaChanged) {
                    if (state.vramWindow.compareAndSet(window, new VramWindow(window.day(), nextCursor, metaSig, window.baselineSent()))) {
                        send(session, Map.of("type", "vram_delta", "payload", payload));
                    }
                }
            } catch (Exception e) {
                log.warn("[ws/stats/v2] vram_delta error: {}", e.getMessage());
            }
        }
    }

    // Whether a vram window snapshot captured on the tick thread is still the
    // state's current window. The reference identity is the check: a
    // transition is a single atomic swap, so a fresh-generation/stale-day
    // pairing — what separate volatile fields allowed when the writer paused
    // between the generation bump and the day write — is not expressible,
    // and any snapshot swapped out is stale whatever it fetched.
    static boolean isCurrentVramWindow(SessionState state, VramWindow snapshot) {
        return state.vramWindow.get() == snapshot;
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
                state.scopeUserId, state.scopeTeamId, state.scopeProviderId, state.scopeErrorsOnly);
            state.bucketSeconds = stats.get("bucketSeconds") instanceof Number n ? n.intValue() : 60;

            send(session, Map.of("type", "timeline_init", "payload", stats));
        } catch (Exception e) {
            send(session, Map.of("type", "timeline_init", "payload", Map.of("error", "Failed to load timeline data")));
        }
    }

    /**
     * Re-send the aggregates for the session's range.
     *
     * Identical in content to {@link #pushTimelineInit}; it is a separate
     * message only so the client can tell a range change (which invalidates
     * what is on screen) from a periodic refresh of the range it already shows.
     */
    private void pushStats(WebSocketSession session, SessionState state) {
        try {
            // A live selection keeps growing, so it has to be queried up to now,
            // the same way pushRequests does. Only the end moves; the start
            // stays where the preset put it.
            if (state.timelineLive) state.timelineEnd = Instant.now().toString();

            Map<String, Object> stats = statsService.getRequestLogStats(
                state.timelineStart, state.timelineEnd, state.targetBuckets,
                state.scopeUserId, state.scopeTeamId, state.scopeProviderId, state.scopeErrorsOnly);
            state.bucketSeconds = stats.get("bucketSeconds") instanceof Number n
                ? n.intValue() : state.bucketSeconds;
            send(session, Map.of("type", "stats", "payload", stats));
        } catch (Exception e) {
            log.warn("[ws/stats/v2] stats push error: {}", e.getMessage());
        }
    }

    private void pushRequests(WebSocketSession session, SessionState state, boolean force) {
        try {
            // A live selection ("last 30 days", "today", …) keeps growing while
            // the page is open, so the request list has to query up to *now*.
            // state.timelineEnd is only moved by a range change, so reading it
            // here would pin the list to the instant the range was set and no
            // request enqueued after page load would ever show up.
            String end = state.timelineLive ? Instant.now().toString() : state.timelineEnd;
            Map<String, Object> payload = requestLogService.getLatestRequests(
                state.timelineStart, end, state.scopeUserId, state.scopeTeamId,
                state.scopeProviderId, state.scopeErrorsOnly,
                state.feedStatus, null, null, LATEST_REQUESTS_PUSH_SIZE, false);
            mergeLiveStreams(payload);
            String sig = requestsSig(payload);
            String idsSig = requestIdsSig(payload);
            boolean changed = !sig.equals(state.prevReqSig);
            boolean rowsChanged = !idsSig.equals(state.prevFeedIdsSig);

            // The aggregates summarise the whole user/team scope, and the page
            // above only shows what its state filter lets through. So a
            // filtered feed's signature changes when its bucket moves — and
            // says nothing when the rest of the scope does. The scope-wide
            // probe below answers that second question: one aggregate over
            // the exact set the aggregates count, no row materialisation.
            boolean scopeMoved = false;
            if (state.feedStatus != null) {
                String scopeSig = requestLogService.scopeMovementSig(
                    state.timelineStart, end, state.scopeUserId, state.scopeTeamId,
                    state.scopeProviderId, state.scopeErrorsOnly);
                if (scopeSig != null && !scopeSig.equals(state.prevScopeSig)) {
                    // The first probe after a fresh baseline (init, scope or
                    // range change re-pushed the aggregates moments ago) just
                    // records the baseline; a move is a change on top of one.
                    scopeMoved = !state.prevScopeSig.isEmpty();
                    state.prevScopeSig = scopeSig;
                }
            }
            if (changed || scopeMoved) {
                // A request arrived, was scheduled, finished, or grew its
                // usage — whatever the aggregates summarise has moved with
                // it. With a state filter on, `changed` only sees that one
                // bucket, so `scopeMoved` carries the signal for the rest of
                // the scope the aggregates still cover.
                state.statsDirty = true;
            }
            if (force || changed) {
                // A status-filtered feed counts itself: the total an unfiltered
                // page borrows from the statistics aggregates is only as narrow
                // as the user/team scope, not the state bucket, so the "of N"
                // would promise rows the filter has hidden. Counting is a range
                // scan, so it runs only when the row set it counts can have
                // moved: a forced push, or a page whose request ids changed.
                // Token values grow without the ids or the count moving, so
                // the figure the last push carried stays valid in between.
                if (state.feedStatus != null && (force || rowsChanged)) {
                    payload.put("total", requestLogService.countFeedRows(
                        state.timelineStart, end, state.scopeUserId, state.scopeTeamId,
                        state.scopeProviderId, state.scopeErrorsOnly,
                        state.feedStatus));
                }
                state.prevReqSig = sig;
                state.prevFeedIdsSig = idsSig;
                send(session, Map.of("type", "requests", "payload", payload));
            }
        } catch (Exception e) {
            log.warn("[ws/stats/v2] requests push error: {}", e.getMessage());
        }
    }

    // How often a live update may cost a DB read and a push per session. The
    // orchestrator emits one per token delta, so without a gate the feed would
    // requery the database at the model's token rate; with it, the numbers
    // still move several times a second, which is what "live" needs.
    private static final long LIVE_PUSH_MIN_INTERVAL_MS = 250;
    private volatile long lastLivePushAtMs = 0;

    /**
     * A fresh live snapshot arrived from the orchestrator.
     *
     * Runs on the client's SSE thread, not the tick thread, and fires once per
     * token delta — so it coalesces to at most one push per interval, and the
     * push itself is the usual change-detected one: a session whose page shows
     * nothing that moved pays a database read and sends nothing.
     */
    private void onLiveUpdate(Map<String, OrchestratorLiveStreamClient.LiveStream> streams) {
        if (streams.isEmpty()) return;  // nothing running; the tick settles the feed
        long now = System.currentTimeMillis();
        if (now - lastLivePushAtMs < LIVE_PUSH_MIN_INTERVAL_MS) return;
        lastLivePushAtMs = now;
        for (Map.Entry<String, WebSocketSession> entry : sessions.entrySet()) {
            WebSocketSession session = entry.getValue();
            SessionState state = states.get(entry.getKey());
            if (state == null || !state.initialized || !session.isOpen()) continue;
            if (!state.wantsRequests()) continue;
            try {
                pushRequests(session, state, false);
            } catch (Exception e) {
                log.warn("[ws/stats/v2] live requests push error for session {}: {}", entry.getKey(), e.getMessage());
            }
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
            // While the request still queues, the prompt figure is the
            // estimate computed from the body, not something the upstream
            // stated — the page shows it as such instead of as fact.
            request.put("prompt_estimated", stream.promptEstimated());
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
    // never reaches the page. The provider and the model in particular move
    // after the first push — the row carries the deployment the request was
    // made for from enqueue time, and the pair that actually serves it is
    // only written once the request is scheduled (and both are re-resolved
    // together once the execution context lands). Without them in the
    // signature, a re-routed request kept showing its queued-time provider
    // while the badge next to it moved on.
    @SuppressWarnings("unchecked")
    static String requestsSig(Map<String, Object> payload) {
        var reqs = (java.util.List<Map<String, Object>>) payload.getOrDefault("requests", java.util.List.of());
        StringBuilder sb = new StringBuilder();
        for (var r : reqs) {
            sb.append(r.getOrDefault("request_id", "")).append(':')
              .append(r.getOrDefault("status", "")).append(':')
              .append(r.getOrDefault("provider_name", "")).append(':')
              // Re-resolved in the same statement as the provider once the
              // execution context lands, so a re-routed request changes its
              // model without any timestamp moving — leaving it out pins the
              // row to the model the request was enqueued for.
              .append(r.getOrDefault("model_name", "")).append(':')
              // Rendered as the Cloud/Local badge, so the same rule as the
              // name applies: a change to it must not be deduplicated away.
              .append(r.getOrDefault("is_cloud", "")).append(':')
              .append(r.getOrDefault("scheduled_ts", "")).append(':')
              .append(r.getOrDefault("request_complete_ts", "")).append(':')
              // Usage and cost grow while a request streams, without any of the
              // fields above changing — leaving them out of the signature pins
              // the token and cost line of a running request to its first push.
              .append(r.getOrDefault("prompt_tokens", "")).append(':')
              .append(r.getOrDefault("prompt_estimated", "")).append(':')
              .append(r.getOrDefault("completion_tokens", "")).append(':')
              .append(r.getOrDefault("total_tokens", "")).append(':')
              .append(r.getOrDefault("cost_microcents", "")).append(',');
        }
        return sb.toString();
    }

    // The page's row set, values excluded: a changed row set is the only
    // moment the feed's own count can have moved, so it gates the range scan
    // that recounts it. Token and cost figures grow on a running request
    // without a single id changing, and the count rides through that.
    @SuppressWarnings("unchecked")
    static String requestIdsSig(Map<String, Object> payload) {
        var reqs = (java.util.List<Map<String, Object>>) payload.getOrDefault("requests", java.util.List.of());
        StringBuilder sb = new StringBuilder();
        for (var r : reqs) sb.append(r.getOrDefault("request_id", "")).append(',');
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


    @PreDestroy
    public void shutdown() { scheduler.shutdownNow(); }
}
