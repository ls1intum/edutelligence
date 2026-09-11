package de.tum.cit.aet.logos.logoswebservice.websocket;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.operations.service.EnqueueEventService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogStatsService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.VramService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorLiveStreamClient;

/**
 * The realtime half of the request feed: an SSE line from the orchestrator
 * must reach an initialised viewer as a websocket push without waiting for
 * the two-second tick. Plain unit test on purpose — no container, no network,
 * the client's SSE loop is fed line by line.
 */
class StatsV2WebSocketHandlerLivePushTest {

    private VramService vramService;
    private RequestLogService requestLogService;
    private RequestLogStatsService statsService;
    private EnqueueEventService enqueueService;
    private OrchestratorLiveStreamClient liveStreamClient;
    private StatsV2WebSocketHandler handler;
    private WebSocketSession session;

    private static Map<String, Object> requestRow(String requestId) {
        Map<String, Object> row = new HashMap<>();
        row.put("request_id", requestId);
        row.put("status", "pending");
        return row;
    }

    /**
     * The real service returns fresh collections per call; the stub must too,
     * because the tick thread and the live-push thread both read the feed.
     * The template is copied per call, so a merge on one push does not leak
     * into the next.
     */
    @SuppressWarnings("unchecked")
    private static void stubLatestRequests(RequestLogService service, Map<String, Object> template) {
        when(service.getLatestRequests(any(), any(), any(), any(), any(), any(), any(), anyInt(), anyBoolean()))
            .thenAnswer(inv -> Map.of("requests", List.of(new HashMap<>(template))));
    }

    @BeforeEach
    void setUp() {
        vramService = mock(VramService.class);
        requestLogService = mock(RequestLogService.class);
        statsService = mock(RequestLogStatsService.class);
        enqueueService = mock(EnqueueEventService.class);
        when(statsService.getRequestLogStats(any(), any(), anyInt(), any(), any()))
            .thenReturn(Map.of("bucketSeconds", 60));
        when(vramService.getVramStats(anyString(), anyInt()))
            .thenReturn(Map.of("providers", List.of(), "last_snapshot_id", 0));
        when(enqueueService.getInRange(any(), any(), anyInt(), any(), any()))
            .thenReturn(Map.of("events", List.of()));

        RestTemplate restTemplate = mock(RestTemplate.class);
        liveStreamClient = new OrchestratorLiveStreamClient(restTemplate);
        ReflectionTestUtils.setField(liveStreamClient, "orchestratorUrl", "http://orchestrator");
        ReflectionTestUtils.setField(liveStreamClient, "internalSecret", "secret");
        // The fallback pull: no streams, so the cache only ever fills from the
        // data lines the tests feed.
        when(restTemplate.exchange(anyString(), any(HttpMethod.class), any(HttpEntity.class), any(Class.class)))
            .thenReturn(ResponseEntity.ok(Map.of("streams", List.of())));

        handler = new StatsV2WebSocketHandler(
            vramService, requestLogService, statsService, enqueueService,
            liveStreamClient, new ObjectMapper());
        stubLatestRequests(requestLogService, requestRow("req-1"));

        session = mock(WebSocketSession.class);
        when(session.getId()).thenReturn("live-push-session");
        when(session.isOpen()).thenReturn(true);
    }

    @AfterEach
    void tearDown() {
        handler.shutdown();
    }

    private void connectAndInit() throws Exception {
        handler.afterConnectionEstablished(session);
        handler.handleMessage(session, new TextMessage("{\"action\":\"init\"}"));
        clearInvocations(session);
    }

    private static Map<String, Object> vramPayload(int lastSnapshotId, String connectionState) {
        Map<String, Object> provider = new HashMap<>();
        provider.put("provider_id", 1);
        provider.put("name", "worker-a");
        provider.put("data", List.of());
        provider.put("connection_state", connectionState);
        provider.put("calibrating", null);
        Map<String, Object> payload = new HashMap<>();
        payload.put("providers", List.of(provider));
        payload.put("last_snapshot_id", lastSnapshotId);
        return payload;
    }

    @Test
    void a_stale_vram_delta_is_dropped_after_a_day_change() throws Exception {
        // Stop the tick scheduler: the test drives pushVramDelta itself, and
        // a concurrent real tick would race for the stubs below.
        handler.shutdown();

        String day1 = "2026-09-01";
        String day2 = "2026-09-02";
        when(vramService.getVramStats(day1, 0)).thenReturn(vramPayload(100, "connected"));

        handler.afterConnectionEstablished(session);
        handler.handleMessage(session, new TextMessage("{\"action\":\"init\",\"vram_day\":\"" + day1 + "\"}"));
        clearInvocations(session);

        // The delta's day1 query (cursor 100) only returns after the
        // operator's set_vram_day has run to completion in the meantime —
        // the exact interleaving the atomic window guards against: the
        // tick thread's in-flight query meets the websocket thread's window
        // change.
        when(vramService.getVramStats(day2, 0)).thenReturn(vramPayload(200, "offline"));
        when(vramService.getVramStats(day1, 100)).thenAnswer(inv -> {
            handler.handleMessage(session, new TextMessage("{\"action\":\"set_vram_day\",\"day\":\"" + day2 + "\"}"));
            return vramPayload(100, "connected");
        });

        StatsV2WebSocketHandler.SessionState state = (StatsV2WebSocketHandler.SessionState)
            ((Map<?, ?>) ReflectionTestUtils.getField(handler, "states")).get(session.getId());
        ReflectionTestUtils.invokeMethod(handler, "pushVramDelta", session, state);

        // The late delta describes day1: it must not be sent, and it must
        // not write day1's cursor or connection-state baseline over the ones
        // day2's init just established.
        assertThat(state.vramWindow.get().cursor()).isEqualTo(200);
        assertThat(state.vramWindow.get().metaSig()).contains("offline").doesNotContain("connected");

        ArgumentCaptor<TextMessage> captor = ArgumentCaptor.forClass(TextMessage.class);
        verify(session, atLeastOnce()).sendMessage(captor.capture());
        assertThat(captor.getAllValues())
            .noneMatch(m -> m.getPayload().contains("\"type\":\"vram_delta\""));
    }

    @Test
    void a_stale_day_with_a_fresh_generation_is_not_a_current_window() {
        // The interleaving the separate volatile fields had to survive — the
        // delta reads the day before set_vram_day runs, the generation after
        // it — is not expressible anymore: the window is one immutable
        // reference, so a snapshot either is the current window or it is
        // not, whatever the writer paused on and whatever the query fetched.
        StatsV2WebSocketHandler.SessionState state = new StatsV2WebSocketHandler.SessionState();
        StatsV2WebSocketHandler.VramWindow stale = new StatsV2WebSocketHandler.VramWindow("2026-09-01", 100, "connected");
        state.vramWindow.set(stale);

        // A snapshot of the window the state is in passes.
        assertThat(StatsV2WebSocketHandler.isCurrentVramWindow(state, stale)).isTrue();

        // The window moves to day2: the old snapshot is stale the moment it
        // is swapped out, whatever the in-flight day1 query fetched for it.
        StatsV2WebSocketHandler.VramWindow current = new StatsV2WebSocketHandler.VramWindow("2026-09-02", 200, "offline");
        state.vramWindow.set(current);
        assertThat(StatsV2WebSocketHandler.isCurrentVramWindow(state, stale)).isFalse();
        // A coherent snapshot of the window the state is in still passes.
        assertThat(StatsV2WebSocketHandler.isCurrentVramWindow(state, current)).isTrue();
        // And a superseded snapshot of the moved-in window does not: a delta
        // paused between its capture and its write-back loses the
        // compareAndSet against the writer's transition.
        assertThat(StatsV2WebSocketHandler.isCurrentVramWindow(
            state, new StatsV2WebSocketHandler.VramWindow("2026-09-02", 0, ""))).isFalse();
    }

    @Test
    void a_live_update_reaches_the_viewer_as_a_requests_push() throws Exception {
        connectAndInit();

        liveStreamClient.handleLine("data: {\"streams\":[{\"request_id\":\"req-1\",\"prompt_tokens\":1200,\"prompt_estimated\":true,\"completion_tokens\":42,\"tokens_per_second\":21.0}]}");

        ArgumentCaptor<TextMessage> captor = ArgumentCaptor.forClass(TextMessage.class);
        verify(session, atLeastOnce()).sendMessage(captor.capture());
        String json = captor.getValue().getPayload();

        assertThat(json).contains("\"type\":\"requests\"");
        assertThat(json).contains("\"prompt_tokens\":1200");
        assertThat(json).contains("\"completion_tokens\":42");
        assertThat(json).contains("\"tokens_per_second\":21.0");
        assertThat(json).contains("\"prompt_estimated\":true");
        assertThat(json).contains("\"streaming\":true");
    }

    @Test
    void a_settled_row_keeps_its_database_usage() throws Exception {
        connectAndInit();
        Map<String, Object> row = requestRow("req-1");
        row.put("total_tokens", 100L);
        stubLatestRequests(requestLogService, row);
        clearInvocations(session);

        liveStreamClient.handleLine("data: {\"streams\":[{\"request_id\":\"req-1\",\"prompt_tokens\":1200,\"completion_tokens\":42}]}");

        ArgumentCaptor<TextMessage> captor = ArgumentCaptor.forClass(TextMessage.class);
        verify(session, atLeastOnce()).sendMessage(captor.capture());
        String json = captor.getValue().getPayload();

        assertThat(json).contains("\"total_tokens\":100");
        assertThat(json).doesNotContain("\"streaming\":true");
    }
}
