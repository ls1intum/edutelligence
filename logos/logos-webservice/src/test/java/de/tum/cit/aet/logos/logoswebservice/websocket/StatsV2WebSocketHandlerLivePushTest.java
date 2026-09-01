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
