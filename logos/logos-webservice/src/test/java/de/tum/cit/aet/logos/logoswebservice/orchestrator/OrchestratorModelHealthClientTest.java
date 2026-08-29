package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.RestTemplate;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * The model breakdown rides on the orchestrator's secret-gated
 * /internal/model_health payload. A webservice deployed against an older
 * orchestrator (no "models" key) has to keep working and simply report no
 * models.
 */
class OrchestratorModelHealthClientTest {

    @SuppressWarnings("unchecked")
    private static ResponseEntity<Map> ok(Map<String, Object> body) {
        return (ResponseEntity<Map>) (ResponseEntity<?>) ResponseEntity.ok(body);
    }

    private static OrchestratorModelHealthClient newClient(RestTemplate restTemplate) {
        OrchestratorModelHealthClient client = new OrchestratorModelHealthClient(restTemplate);
        ReflectionTestUtils.setField(client, "orchestratorUrl", "http://orchestrator");
        ReflectionTestUtils.setField(client, "internalSecret", "secret");
        return client;
    }

    private OrchestratorModelHealthClient clientReturning(Map<String, Object> body) {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(
                any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenReturn(ok(body));
        return newClient(restTemplate);
    }

    @Test
    void readsModelEntriesFromHealthPayload() {
        Map<String, Object> models = new LinkedHashMap<>();
        models.put("models", List.of(
            Map.of("name", "gpt-4", "status", "UP"),
            Map.of("name", "llama-3.1-8b", "status", "DEGRADED")
        ));

        List<Map<String, Object>> health = clientReturning(models).getModelHealth();

        assertThat(health).hasSize(2);
        assertThat(health.get(0)).containsEntry("name", "gpt-4").containsEntry("status", "UP");
        assertThat(health.get(1)).containsEntry("name", "llama-3.1-8b").containsEntry("status", "DEGRADED");
    }

    @Test
    void sendsInternalSecretAndTargetsInternalPath() {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenReturn(ok(Map.of("models", List.of(Map.of("name", "gpt-4", "status", "UP")))));
        OrchestratorModelHealthClient client = newClient(restTemplate);

        client.getModelHealth();

        ArgumentCaptor<String> url = ArgumentCaptor.forClass(String.class);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<HttpEntity<Void>> entity = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).exchange(url.capture(), eq(HttpMethod.GET), entity.capture(), eq(Map.class));
        assertThat(url.getValue()).isEqualTo("http://orchestrator/internal/model_health");
        assertThat(entity.getValue().getHeaders().getFirst("Authorization")).isEqualTo("Bearer secret");
    }

    @Test
    void toleratesOlderOrchestratorWithoutModels() {
        // Pre-rework payload shape: service-level fields only.
        List<Map<String, Object>> health = clientReturning(Map.of(
            "status", "DOWN",
            "local_models", "DOWN",
            "cloud_models", "UP",
            "detail", "No local provider with a capable model is online. Cloud models may still be served."
        )).getModelHealth();

        assertThat(health).isEmpty();
    }

    @Test
    void skipsMalformedEntries() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("models", List.of(
            "not-a-map",
            Map.of("name", "gpt-4", "status", "UP")
        ));

        List<Map<String, Object>> health = clientReturning(body).getModelHealth();

        assertThat(health).hasSize(1);
        assertThat(health.get(0)).containsEntry("name", "gpt-4");
    }

    @Test
    void readsModelEntriesFrom503BodyWhenLocalWorkersAreDown() {
        // /health answers 503 while every local worker is down, but its body
        // still carries the model breakdown (cloud models may be serveable).
        String body = "{\"status\":\"DOWN\",\"local_models\":\"DOWN\",\"cloud_models\":\"UP\","
            + "\"models\":[{\"name\":\"gpt-4\",\"status\":\"UP\"}]}";
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenThrow(new HttpClientErrorException(
                HttpStatusCode.valueOf(503), "Service Unavailable", new HttpHeaders(),
                body.getBytes(StandardCharsets.UTF_8), StandardCharsets.UTF_8));
        OrchestratorModelHealthClient client = newClient(restTemplate);

        List<Map<String, Object>> health = client.getModelHealth();

        assertThat(health).hasSize(1);
        assertThat(health.get(0)).containsEntry("name", "gpt-4").containsEntry("status", "UP");
    }

    @Test
    void clearsStaleEntriesWhenModelsKeyDisappears() {
        Map<String, Object> withModels = Map.of("models", List.of(Map.of("name", "gpt-4", "status", "UP")));
        Map<String, Object> withoutModels = Map.of("status", "DOWN");
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenReturn(ok(withModels), ok(withoutModels));
        OrchestratorModelHealthClient client = newClient(restTemplate);

        assertThat(client.getModelHealth()).hasSize(1);
        ReflectionTestUtils.setField(client, "cachedAtMs", 0L); // bypass the cache TTL
        assertThat(client.getModelHealth()).isEmpty();
    }

    @Test
    void empty500ResponsePreservesCachedHealth() {
        Map<String, Object> withModels = Map.of("models", List.of(Map.of("name", "gpt-4", "status", "UP")));
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenReturn(ok(withModels))
            .thenThrow(new HttpServerErrorException(
                HttpStatus.INTERNAL_SERVER_ERROR, "Internal Server Error", new HttpHeaders(),
                new byte[0], StandardCharsets.UTF_8));
        OrchestratorModelHealthClient client = newClient(restTemplate);

        assertThat(client.getModelHealth()).hasSize(1);
        ReflectionTestUtils.setField(client, "cachedAtMs", 0L); // bypass the cache TTL
        assertThat(client.getModelHealth()).hasSize(1);
    }

    @Test
    void malformed503ResponsePreservesCachedHealth() {
        Map<String, Object> withModels = Map.of("models", List.of(Map.of("name", "gpt-4", "status", "UP")));
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenReturn(ok(withModels))
            .thenThrow(new HttpClientErrorException(
                HttpStatusCode.valueOf(503), "Service Unavailable", new HttpHeaders(),
                "<html>nope</html>".getBytes(StandardCharsets.UTF_8), StandardCharsets.UTF_8));
        OrchestratorModelHealthClient client = newClient(restTemplate);

        assertThat(client.getModelHealth()).hasSize(1);
        ReflectionTestUtils.setField(client, "cachedAtMs", 0L); // bypass the cache TTL
        assertThat(client.getModelHealth()).hasSize(1);
    }

    @Test
    void non503ErrorKeepsCacheWindow() {
        Map<String, Object> withModels = Map.of("models", List.of(Map.of("name", "gpt-4", "status", "UP")));
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenReturn(ok(withModels))
            .thenThrow(new HttpServerErrorException(
                HttpStatus.INTERNAL_SERVER_ERROR, "Internal Server Error", new HttpHeaders(),
                new byte[0], StandardCharsets.UTF_8));
        OrchestratorModelHealthClient client = newClient(restTemplate);

        assertThat(client.getModelHealth()).hasSize(1);
        ReflectionTestUtils.setField(client, "cachedAtMs", 0L); // bypass the cache TTL
        assertThat(client.getModelHealth()).hasSize(1); // 500, cache kept
        assertThat(client.getModelHealth()).hasSize(1); // still inside the cache window

        // The 500 refreshed the cache window: two round trips, not one per call.
        verify(restTemplate, times(2)).exchange(
            any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class));
    }

    @Test
    void unusable503ModelListPreservesCachedHealth() {
        // A 503 whose models list carries no valid entry is unusable garbage —
        // it must not wipe the last known state.
        Map<String, Object> withModels = Map.of("models", List.of(Map.of("name", "gpt-4", "status", "UP")));
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenReturn(ok(withModels))
            .thenThrow(new HttpClientErrorException(
                HttpStatusCode.valueOf(503), "Service Unavailable", new HttpHeaders(),
                "{\"status\":\"DOWN\",\"models\":[\"not-a-map\"],\"detail\":\"No local provider with a capable model is online.\"}"
                    .getBytes(StandardCharsets.UTF_8),
                StandardCharsets.UTF_8));
        OrchestratorModelHealthClient client = newClient(restTemplate);

        assertThat(client.getModelHealth()).hasSize(1);
        ReflectionTestUtils.setField(client, "cachedAtMs", 0L); // bypass the cache TTL
        assertThat(client.getModelHealth()).hasSize(1);
    }

    @Test
    void empty503ModelListClearsCachedHealth() {
        // In contrast, an explicit models: [] is a valid (empty) breakdown.
        Map<String, Object> withModels = Map.of("models", List.of(Map.of("name", "gpt-4", "status", "UP")));
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenReturn(ok(withModels))
            .thenThrow(new HttpClientErrorException(
                HttpStatusCode.valueOf(503), "Service Unavailable", new HttpHeaders(),
                "{\"status\":\"DOWN\",\"models\":[]}".getBytes(StandardCharsets.UTF_8),
                StandardCharsets.UTF_8));
        OrchestratorModelHealthClient client = newClient(restTemplate);

        assertThat(client.getModelHealth()).hasSize(1);
        ReflectionTestUtils.setField(client, "cachedAtMs", 0L); // bypass the cache TTL
        assertThat(client.getModelHealth()).isEmpty();
    }

    @Test
    void entriesAreReducedToNameAndStatus() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("models", List.of(
            Map.of("name", "gpt-4", "status", "UP", "provider_id", 7, "provider_name", "gpu-node-1"),
            Map.of("name", "missing-status"),
            "not-a-map"
        ));

        List<Map<String, Object>> health = clientReturning(body).getModelHealth();

        assertThat(health).hasSize(1);
        assertThat(health.get(0)).containsOnlyKeys("name", "status");
        assertThat(health.get(0)).containsEntry("name", "gpt-4");
    }
}
