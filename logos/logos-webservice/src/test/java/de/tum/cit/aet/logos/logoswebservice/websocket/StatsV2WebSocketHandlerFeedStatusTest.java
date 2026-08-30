package de.tum.cit.aet.logos.logoswebservice.websocket;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.stubbing.Answer;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.operations.service.EnqueueEventService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogStatsService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.VramService;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorLiveStreamClient;

/**
 * The bookkeeping around the feed's state filter.
 *
 * Two things the filter must not break: the aggregates' dirty signal has to
 * stay scope-wide while the page is narrowed to one bucket, and the bucket's
 * own count must not be re-scanned on every token delta. Plain unit test, the
 * same way the live-push one is built — and the handler's background tick is
 * stopped, because these tests drive {@code tick()} and {@code pushRequests}
 * themselves and would otherwise race a second caller on the same session.
 */
class StatsV2WebSocketHandlerFeedStatusTest {

    private VramService vramService;
    private RequestLogService requestLogService;
    private RequestLogStatsService statsService;
    private EnqueueEventService enqueueService;
    private StatsV2WebSocketHandler handler;
    private WebSocketSession session;
    private ObjectMapper objectMapper;
    private final List<TextMessage> sent = new ArrayList<>();

    /** The rows the service stub serves; the answer copies them per call. */
    private List<Map<String, Object>> servedRows = List.of();

    @BeforeEach
    void setUp() throws Exception {
        objectMapper = new ObjectMapper();
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
        when(enqueueService.getDeltas(any(), any(), any(), anyInt(), any(), any()))
            .thenReturn(Map.of("events", List.of(), "cursor", Map.of("enqueue_ts", "", "request_id", "")));
        // A fresh, mutable payload per call — the push writes "total" into it
        // while a filter is on, and the real service returns a fresh map too.
        when(requestLogService.getLatestRequests(
                any(), any(), any(), any(), any(), any(), any(), anyInt(), anyBoolean()))
            .thenAnswer(inv -> {
                Map<String, Object> payload = new LinkedHashMap<>();
                payload.put("requests", servedRows.stream().map(HashMap::new).toList());
                payload.put("has_more", false);
                payload.put("next_cursor", null);
                return payload;
            });

        RestTemplate restTemplate = mock(RestTemplate.class);
        OrchestratorLiveStreamClient liveStreamClient = new OrchestratorLiveStreamClient(restTemplate);
        ReflectionTestUtils.setField(liveStreamClient, "orchestratorUrl", "http://orchestrator");
        ReflectionTestUtils.setField(liveStreamClient, "internalSecret", "secret");
        // No streams: the live merge stays out of these tests.
        when(restTemplate.exchange(anyString(), any(HttpMethod.class), any(HttpEntity.class), any(Class.class)))
            .thenReturn(ResponseEntity.ok(Map.of("streams", List.of())));

        handler = new StatsV2WebSocketHandler(
            vramService, requestLogService, statsService, enqueueService,
            liveStreamClient, objectMapper);
        // The tests below drive the tick themselves; the scheduled one would
        // advance the same session in between.
        handler.shutdown();

        session = mock(WebSocketSession.class);
        when(session.getId()).thenReturn("feed-status-session");
        when(session.isOpen()).thenReturn(true);
        doAnswer((Answer<Void>) inv -> {
            sent.add(inv.<TextMessage>getArgument(0));
            return null;
        }).when(session).sendMessage(any());
    }

    @AfterEach
    void tearDown() {
        handler.shutdown();
    }

    private void connectAndInit() throws Exception {
        handler.afterConnectionEstablished(session);
        handler.handleMessage(session, new TextMessage("{\"action\":\"init\"}"));
        sent.clear();
    }

    private static Map<String, Object> row(String id, Object totalTokens) {
        // The token figure exists only to move the page's signature between
        // two pushes of the same row set.
        Map<String, Object> r = new HashMap<>();
        r.put("request_id", id);
        r.put("status", "queued");
        r.put("total_tokens", totalTokens);
        return r;
    }

    @SuppressWarnings("unchecked")
    private void invokeTick() {
        ReflectionTestUtils.invokeMethod(handler, "tick");
    }

    @SuppressWarnings("unchecked")
    private void invokePushRequests(boolean force) {
        Map<String, Object> states = (Map<String, Object>) ReflectionTestUtils.getField(handler, "states");
        ReflectionTestUtils.invokeMethod(handler, "pushRequests", session, states.get(session.getId()), force);
    }

    private List<String> pushedTypes() throws Exception {
        List<String> types = new ArrayList<>();
        for (TextMessage m : sent) {
            JsonNode node = objectMapper.readTree(m.getPayload());
            types.add(node.path("type").asText());
        }
        return types;
    }

    @Test
    void a_filtered_session_refreshes_its_aggregates_when_out_of_bucket_traffic_moves() throws Exception {
        servedRows = List.of(row("req-1", null));
        connectAndInit();

        // A stable scope: the probe repeats its fingerprint, and the feed
        // counts its one queued row.
        when(requestLogService.scopeMovementSig(any(), any(), any(), any()))
            .thenReturn("6;2026-08-29T21:00:00Z");
        when(requestLogService.countFeedRows(any(), any(), any(), any(), any())).thenReturn(1L);

        handler.handleMessage(session, new TextMessage("{\"action\":\"set_feed_status\",\"status\":\"queued\"}"));
        assertThat(pushedTypes()).containsExactly("requests");
        sent.clear();

        // The init push marked the feed changed, so the first aggregate gate
        // after connect still delivers the opening aggregates. Let that drain
        // so the assertions below see only what the filter's bookkeeping does.
        ReflectionTestUtils.setField(handler, "globalTick", 10);
        invokeTick();
        assertThat(pushedTypes()).containsExactly("stats");
        sent.clear();

        // A tick that reaches the aggregate gate: nothing in scope moved, so
        // nothing goes out.
        ReflectionTestUtils.setField(handler, "globalTick", 20);
        invokeTick();
        assertThat(pushedTypes()).isEmpty();

        // Out-of-bucket traffic moves — the scope's newest event advances
        // while the queued page is untouched, so the feed's own signature
        // stays put and only the probe reports it.
        when(requestLogService.scopeMovementSig(any(), any(), any(), any()))
            .thenReturn("6;2026-08-29T21:05:00Z");
        ReflectionTestUtils.setField(handler, "globalTick", 30);
        invokeTick();

        // The aggregates go out for the whole scope; the page did not change,
        // so no requests push rides along.
        assertThat(pushedTypes()).containsExactly("stats");
    }

    @Test
    void the_bucket_count_is_recounted_only_when_the_row_set_moves() throws Exception {
        connectAndInit();

        when(requestLogService.scopeMovementSig(any(), any(), any(), any()))
            .thenReturn("1;2026-08-29T21:00:00Z");
        when(requestLogService.countFeedRows(any(), any(), any(), any(), any())).thenReturn(1L);

        servedRows = List.of(row("req-1", 100));
        handler.handleMessage(session, new TextMessage("{\"action\":\"set_feed_status\",\"status\":\"queued\"}"));
        // The forced push after a filter change counts the bucket.
        verify(requestLogService, times(1)).countFeedRows(any(), any(), any(), any(), any());
        clearInvocations(requestLogService);
        sent.clear();

        // Only the token count grows: the page changes, the row set does not,
        // and the count cannot have moved with the tokens.
        servedRows = List.of(row("req-1", 101));
        invokePushRequests(false);
        assertThat(pushedTypes()).containsExactly("requests");
        verify(requestLogService, never()).countFeedRows(any(), any(), any(), any(), any());
        sent.clear();

        // A second queued row appears: the row set has moved, so the count is
        // re-queried.
        servedRows = List.of(row("req-1", 101), row("req-2", 40));
        invokePushRequests(false);
        assertThat(pushedTypes()).containsExactly("requests");
        verify(requestLogService, times(1)).countFeedRows(any(), any(), any(), any(), any());
    }
}
