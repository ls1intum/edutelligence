package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.LinkedHashMap;
import java.util.List;
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

/**
 * The model breakdown rides on the orchestrator's public /health payload. A
 * webservice deployed against an older orchestrator (no "models" key) has to
 * keep working and simply report no models.
 */
class OrchestratorModelHealthClientTest {

    @SuppressWarnings("unchecked")
    private OrchestratorModelHealthClient clientReturning(Map<String, Object> body) {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(
                any(String.class), eq(HttpMethod.GET), any(HttpEntity.class), eq(Map.class)))
            .thenReturn((ResponseEntity<Map>) (ResponseEntity<?>) ResponseEntity.ok(body));
        OrchestratorModelHealthClient client = new OrchestratorModelHealthClient(restTemplate);
        ReflectionTestUtils.setField(client, "orchestratorUrl", "http://orchestrator");
        return client;
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
}
