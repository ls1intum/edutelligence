package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.LinkedHashMap;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorModelWindowClient.ModelContextWindows;

/**
 * The orchestrator reports three context windows per model. The AI-tools page
 * needs all three, and a webservice deployed against an older orchestrator has
 * to keep working with only the one it used to send.
 */
class OrchestratorModelWindowClientTest {

    @SuppressWarnings("unchecked")
    private OrchestratorModelWindowClient clientReturning(Map<String, Object> body) {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(
                any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenReturn((ResponseEntity<Map>) (ResponseEntity<?>) ResponseEntity.ok(body));
        OrchestratorModelWindowClient client = new OrchestratorModelWindowClient(restTemplate);
        ReflectionTestUtils.setField(client, "orchestratorUrl", "http://orchestrator");
        ReflectionTestUtils.setField(client, "internalSecret", "secret");
        return client;
    }

    private static Map<String, Object> stats(Object... entries) {
        Map<String, Object> byModel = new LinkedHashMap<>();
        for (int i = 0; i < entries.length; i += 2) {
            byModel.put((String) entries[i], entries[i + 1]);
        }
        return Map.of("stats", byModel);
    }

    @Test
    void readsAllThreeWindows() {
        var client = clientReturning(stats(
            "qwen-27b", Map.of("current_min", 33000, "current_max", 262144, "overall", 262144)));

        ModelContextWindows windows = client.getContextWindows().get("qwen-27b");

        assertThat(windows.currentMin()).isEqualTo(33000);
        assertThat(windows.currentMax()).isEqualTo(262144);
        assertThat(windows.overall()).isEqualTo(262144);
    }

    @Test
    void keepsPartialEntries() {
        // A model with a profile but nothing loaded reports only its own limit.
        var client = clientReturning(stats("cold-model", Map.of("overall", 131072)));

        ModelContextWindows windows = client.getContextWindows().get("cold-model");

        assertThat(windows.currentMin()).isNull();
        assertThat(windows.currentMax()).isNull();
        assertThat(windows.overall()).isEqualTo(131072);
    }

    @Test
    void dropsEntriesWithNothingUsable() {
        var client = clientReturning(stats(
            "broken", Map.of("current_min", 0, "current_max", -5, "overall", "lots")));

        assertThat(client.getContextWindows()).doesNotContainKey("broken");
    }

    @Test
    void fallsBackToTheFlatWindowsMapFromAnOlderOrchestrator() {
        // Before "stats" existed the endpoint sent model -> smallest window only.
        // That value is the one that always holds, so it becomes currentMin; the
        // other two stay unknown rather than being guessed from it.
        var client = clientReturning(Map.of("windows", Map.of("qwen-14b", 40960)));

        ModelContextWindows windows = client.getContextWindows().get("qwen-14b");

        assertThat(windows.currentMin()).isEqualTo(40960);
        assertThat(windows.currentMax()).isNull();
        assertThat(windows.overall()).isNull();
    }

    @Test
    void returnsEmptyWhenTheOrchestratorIsUnreachable() {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(
                any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenThrow(new RuntimeException("connection refused"));
        OrchestratorModelWindowClient client = new OrchestratorModelWindowClient(restTemplate);
        ReflectionTestUtils.setField(client, "orchestratorUrl", "http://orchestrator");
        ReflectionTestUtils.setField(client, "internalSecret", "secret");

        // Model listings must still render; they just lose the enrichment.
        assertThat(client.getContextWindows()).isEmpty();
    }
}
