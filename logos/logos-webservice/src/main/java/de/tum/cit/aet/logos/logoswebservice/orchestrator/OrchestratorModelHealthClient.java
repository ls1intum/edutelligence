package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

/**
 * Fetches the live model-level health check from the orchestrator. Lane
 * state (warm/sleeping/cold), worker connection state, and node health exist
 * only in the orchestrator's worker registry, so the public
 * get_model_health endpoint is served from this client.
 */
@Service
public class OrchestratorModelHealthClient {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorModelHealthClient.class);
    private static final long CACHE_TTL_MS = 3_000;

    private final RestTemplate restTemplate;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    private volatile List<Map<String, Object>> cached = List.of();
    private volatile long cachedAtMs = 0;

    public OrchestratorModelHealthClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * Model health entries (model_id, name, status, deployments) for every
     * model the orchestrator knows. Returns the last cached result (possibly
     * empty) when the orchestrator is unreachable, so health serving never
     * fails on the round trip.
     */
    public List<Map<String, Object>> getModelHealth() {
        long now = System.currentTimeMillis();
        if (now - cachedAtMs < CACHE_TTL_MS) {
            return cached;
        }
        if (orchestratorUrl.isBlank() || internalSecret.isBlank()) {
            return cached;
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("Authorization", "Bearer " + internalSecret);
            var response = restTemplate.exchange(
                orchestratorUrl + "/internal/model_health",
                HttpMethod.GET,
                new HttpEntity<Void>(headers),
                Map.class);
            Object rawModels = response.getBody() != null ? response.getBody().get("models") : null;
            if (rawModels instanceof List<?> models) {
                List<Map<String, Object>> typed = new ArrayList<>();
                for (Object item : models) {
                    if (item instanceof Map<?, ?> entry) {
                        @SuppressWarnings("unchecked")
                        Map<String, Object> model = (Map<String, Object>) entry;
                        typed.add(model);
                    }
                }
                cached = List.copyOf(typed);
            }
        } catch (Exception e) {
            log.warn("Failed to fetch model health from orchestrator: {}", e.getMessage());
        }
        cachedAtMs = now;
        return cached;
    }
}
