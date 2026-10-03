package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * The admin UI settles an accepted model refresh only on an explicit
 * "not running" from the orchestrator. Every other outcome — a transient
 * timeout, a rolling deploy still running an orchestrator without the
 * endpoint, a malformed body — has to read as unknown, so the distinction
 * this test pins down is false versus null, not true versus false.
 */
class OrchestratorModelSyncClientTest {

    @SuppressWarnings("unchecked")
    private static RestTemplate restTemplateAnswering(Map<String, Object> body) {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(
                any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenReturn((ResponseEntity<Map>) (ResponseEntity<?>) ResponseEntity.ok(body));
        return restTemplate;
    }

    private static OrchestratorModelSyncClient client(RestTemplate restTemplate, String url, String secret) {
        OrchestratorModelSyncClient client = new OrchestratorModelSyncClient(restTemplate);
        ReflectionTestUtils.setField(client, "orchestratorUrl", url);
        ReflectionTestUtils.setField(client, "internalSecret", secret);
        return client;
    }

    @Test
    void reportsRunningWhileAPassIsInFlight() {
        var client = client(restTemplateAnswering(Map.of("running", true)), "http://orchestrator", "secret");

        assertThat(client.isSyncRunning()).isTrue();
    }

    @Test
    void reportsNotRunningOnAnExplicitIdleAnswer() {
        var client = client(restTemplateAnswering(Map.of("running", false)), "http://orchestrator", "secret");

        assertThat(client.isSyncRunning()).isFalse();
    }

    @Test
    void reportsUnknownWhenTheOrchestratorIsUnreachable() {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(
                any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenThrow(new ResourceAccessException("connect timed out"));
        var client = client(restTemplate, "http://orchestrator", "secret");

        // A failed read must not settle an accepted refresh: null, not false.
        assertThat(client.isSyncRunning()).isNull();
    }

    @Test
    void reportsUnknownWhenNoOrchestratorIsConfigured() {
        var client = client(mock(RestTemplate.class), "", "");

        assertThat(client.isSyncRunning()).isNull();
    }

    @Test
    void reportsUnknownWhenTheAnswerCarriesNoUsableState() {
        // An orchestrator that answers but without the running flag (a
        // malformed or partial body) did not report idle either.
        var client = client(restTemplateAnswering(Map.of("status", "weird")), "http://orchestrator", "secret");

        assertThat(client.isSyncRunning()).isNull();
    }
}
