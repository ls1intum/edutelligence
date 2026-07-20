package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.LinkedHashMap;
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
 * Fetches the served context window per model from the orchestrator. The
 * effective window (e.g. vLLM's --max-model-len) exists only in the worker
 * runtime snapshots held by the orchestrator's registry, so model listings
 * that need it (the OpenCode setup page) are enriched from this client.
 */
@Service
public class OrchestratorModelWindowClient {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorModelWindowClient.class);
    private static final long CACHE_TTL_MS = 30_000;

    private final RestTemplate restTemplate;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    private volatile Map<String, Integer> cached = Map.of();
    private volatile long cachedAtMs = 0;

    public OrchestratorModelWindowClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * Served context window (tokens) keyed by model name. Returns the last
     * cached result (possibly empty) when the orchestrator is unreachable, so
     * model listings never fail on enrichment.
     */
    public Map<String, Integer> getContextWindows() {
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
                orchestratorUrl + "/internal/model_context_windows",
                HttpMethod.GET,
                new HttpEntity<Void>(headers),
                Map.class);
            Map<String, Integer> windows = new LinkedHashMap<>();
            Object raw = response.getBody() != null ? response.getBody().get("windows") : null;
            if (raw instanceof Map<?, ?> byModel) {
                for (Map.Entry<?, ?> entry : byModel.entrySet()) {
                    if (entry.getKey() instanceof String model && entry.getValue() instanceof Number window
                            && window.intValue() > 0) {
                        windows.put(model, window.intValue());
                    }
                }
            }
            cached = windows;
        } catch (Exception e) {
            log.warn("Failed to fetch model context windows from orchestrator: {}", e.getMessage());
        }
        cachedAtMs = now;
        return cached;
    }
}
