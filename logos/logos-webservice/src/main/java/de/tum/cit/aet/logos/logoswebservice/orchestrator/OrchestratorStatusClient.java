package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.LinkedHashMap;
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
 * Fetches live provider connection state from the orchestrator's worker
 * registry. Persisted snapshots cannot tell whether a provider is currently
 * online — only the orchestrator (which holds the worker WebSocket sessions)
 * knows, so the statistics payloads are enriched from this client.
 */
@Service
public class OrchestratorStatusClient {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorStatusClient.class);
    private static final long CACHE_TTL_MS = 3_000;

    private final RestTemplate restTemplate;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    private volatile Map<Integer, Map<String, Object>> cached = Map.of();
    private volatile long cachedAtMs = 0;

    public OrchestratorStatusClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * Provider connection metadata keyed by provider id. Returns the last
     * cached result (possibly empty) when the orchestrator is unreachable, so
     * statistics serving never fails on enrichment.
     */
    public Map<Integer, Map<String, Object>> getProviderStatusById() {
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
                orchestratorUrl + "/internal/provider_status",
                HttpMethod.GET,
                new HttpEntity<Void>(headers),
                Map.class);
            Map<Integer, Map<String, Object>> byId = new LinkedHashMap<>();
            Object rawProviders = response.getBody() != null ? response.getBody().get("providers") : null;
            if (rawProviders instanceof List<?> providers) {
                for (Object item : providers) {
                    if (!(item instanceof Map<?, ?> provider)) continue;
                    Object pid = provider.get("provider_id");
                    if (!(pid instanceof Number n)) continue;
                    @SuppressWarnings("unchecked")
                    Map<String, Object> typed = (Map<String, Object>) provider;
                    byId.put(n.intValue(), typed);
                }
            }
            cached = byId;
        } catch (Exception e) {
            log.warn("Failed to fetch provider status from orchestrator: {}", e.getMessage());
        }
        cachedAtMs = now;
        return cached;
    }
}
