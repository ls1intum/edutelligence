package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

/**
 * Plain unit tests for the client; the SSE loop itself is exercised line by
 * line, which is all the handler tests downstream need as well.
 */
class OrchestratorLiveStreamClientTest {

    private RestTemplate restTemplate;
    private OrchestratorLiveStreamClient client;

    @BeforeEach
    void setUp() {
        restTemplate = mock(RestTemplate.class);
        client = new OrchestratorLiveStreamClient(restTemplate);
        ReflectionTestUtils.setField(client, "orchestratorUrl", "http://orchestrator");
        ReflectionTestUtils.setField(client, "internalSecret", "secret");
    }

    @SuppressWarnings("unchecked")
    private void stubPull(Map<String, Object> body) {
        when(restTemplate.exchange(
            eq("http://orchestrator/internal/live_streams"),
            eq(HttpMethod.GET),
            any(HttpEntity.class),
            eq(Map.class)))
            .thenReturn(ResponseEntity.ok(body));
    }

    @Test
    void unconfigured_returnsEmptyWithoutCalling() {
        ReflectionTestUtils.setField(client, "orchestratorUrl", "");

        assertThat(client.getLiveStreams()).isEmpty();

        verifyNoInteractions(restTemplate);
    }

    @Test
    void pull_maps_every_field_of_a_row() {
        stubPull(Map.of("streams", List.of(Map.of(
            "request_id", "req-1",
            "prompt_tokens", 1200,
            "prompt_estimated", true,
            "completion_tokens", 42,
            "tokens_per_second", 21.0))));

        Map<String, OrchestratorLiveStreamClient.LiveStream> streams = client.getLiveStreams();

        assertThat(streams).containsOnlyKeys("req-1");
        assertThat(streams.get("req-1"))
            .isEqualTo(new OrchestratorLiveStreamClient.LiveStream(1200, 42, 21.0, true));
    }

    @Test
    void pull_failure_yields_empty() {
        when(restTemplate.exchange(anyString(), any(HttpMethod.class), any(HttpEntity.class), eq(Map.class)))
            .thenThrow(new ResourceAccessException("down", new IOException("refused")));

        assertThat(client.getLiveStreams()).isEmpty();
    }

    @Test
    void a_data_line_updates_the_cache_and_notifies_the_listener() {
        AtomicReference<Map<String, OrchestratorLiveStreamClient.LiveStream>> seen = new AtomicReference<>();
        client.setOnLiveUpdate(seen::set);

        client.handleLine("data: {\"streams\":[{\"request_id\":\"req-1\",\"prompt_tokens\":1200,\"prompt_estimated\":true,\"completion_tokens\":7}]}");

        // Served from the cache: a fresh snapshot costs no HTTP call.
        Map<String, OrchestratorLiveStreamClient.LiveStream> cached = client.getLiveStreams();
        assertThat(cached.get("req-1"))
            .isEqualTo(new OrchestratorLiveStreamClient.LiveStream(1200, 7, null, true));
        assertThat(seen.get()).isEqualTo(cached);
        verifyNoInteractions(restTemplate);
    }

    @Test
    void a_heartbeat_keeps_the_cache_fresh_and_stays_silent() {
        AtomicInteger notifications = new AtomicInteger();
        client.setOnLiveUpdate(streams -> notifications.incrementAndGet());

        client.handleLine("data: {\"streams\":[{\"request_id\":\"req-1\",\"prompt_tokens\":1,\"completion_tokens\":1}]}");
        client.handleLine(": ping");

        Map<String, OrchestratorLiveStreamClient.LiveStream> cached = client.getLiveStreams();
        assertThat(cached).containsKey("req-1");
        assertThat(notifications).hasValue(1);  // the ping changed nothing
        verifyNoInteractions(restTemplate);
    }

    @Test
    void a_malformed_data_line_is_ignored() {
        stubPull(Map.of("streams", List.of()));

        client.handleLine("data: not-json");

        // No cache entry was born from it, so the read pulls.
        assertThat(client.getLiveStreams()).isEmpty();
    }

    @Test
    void a_newer_snapshot_replaces_the_older_one() {
        client.handleLine("data: {\"streams\":[{\"request_id\":\"req-1\",\"prompt_tokens\":10,\"completion_tokens\":1}]}");
        client.handleLine("data: {\"streams\":[{\"request_id\":\"req-1\",\"prompt_tokens\":10,\"completion_tokens\":9}]}");

        Map<String, OrchestratorLiveStreamClient.LiveStream> cached = client.getLiveStreams();
        assertThat(cached.get("req-1").completionTokens()).isEqualTo(9);
    }
}
