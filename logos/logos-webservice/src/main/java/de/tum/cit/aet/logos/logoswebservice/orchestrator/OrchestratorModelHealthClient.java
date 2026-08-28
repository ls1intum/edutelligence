package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestTemplate;

/**
 * Fetches the live model-level health check from the orchestrator's public
 * /health endpoint. Lane state, worker connection state, and node health
 * exist only in the orchestrator's worker registry, so the public
 * get_model_health endpoint is served from this client.
 */
@Service
public class OrchestratorModelHealthClient {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorModelHealthClient.class);
    private static final long CACHE_TTL_MS = 3_000;
    private static final ObjectMapper JSON = new ObjectMapper();

    private final RestTemplate restTemplate;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    private volatile List<Map<String, Object>> cached = List.of();
    private volatile long cachedAtMs = 0;

    public OrchestratorModelHealthClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * Model health entries (name, status) for every model the orchestrator
     * knows. /health answers 503 while every local worker is down, but its
     * body still carries the model breakdown (cloud models may be serveable),
     * so that body is read as well. Only when the orchestrator is unreachable
     * at all is the last cached result (possibly empty) returned instead, so
     * health serving never fails on the round trip.
     */
    public List<Map<String, Object>> getModelHealth() {
        long now = System.currentTimeMillis();
        if (now - cachedAtMs < CACHE_TTL_MS) {
            return cached;
        }
        if (orchestratorUrl.isBlank()) {
            return cached;
        }
        try {
            Object body;
            try {
                var response = restTemplate.exchange(
                    orchestratorUrl + "/health",
                    HttpMethod.GET,
                    new HttpEntity<Void>(new HttpHeaders()),
                    Map.class);
                body = response.getBody();
            } catch (HttpStatusCodeException e) {
                // 503 = every local worker is down; the response body still
                // carries the model breakdown, so read it instead of
                // discarding it.
                body = parseBody(e.getResponseBodyAsString());
            }
            cached = toModelEntries(body);
        } catch (Exception e) {
            log.warn("Failed to fetch model health from orchestrator: {}", e.getMessage());
        }
        cachedAtMs = now;
        return cached;
    }

    /**
     * Extracts the model entries from a /health body. A body without a
     * "models" list (older orchestrator) yields no entries so stale ones are
     * not served, and each entry is reduced to exactly the two public fields
     * — extra keys the orchestrator might add later never reach the API.
     */
    private static List<Map<String, Object>> toModelEntries(Object body) {
        Object rawModels = body instanceof Map<?, ?> map ? map.get("models") : null;
        if (!(rawModels instanceof List<?> models)) {
            return List.of();
        }
        List<Map<String, Object>> typed = new ArrayList<>();
        for (Object item : models) {
            if (!(item instanceof Map<?, ?> entry)) {
                continue;
            }
            Object name = entry.get("name");
            Object status = entry.get("status");
            if (name == null || status == null) {
                continue;
            }
            typed.add(Map.of("name", name, "status", status));
        }
        return List.copyOf(typed);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> parseBody(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        try {
            return JSON.readValue(raw, Map.class);
        } catch (Exception e) {
            return null;
        }
    }
}
