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
 * Fetches the served context windows per model from the orchestrator. The
 * effective window (e.g. vLLM's --max-model-len) exists only in the worker
 * runtime snapshots held by the orchestrator's registry, so model listings
 * that need it (the AI-tools setup page) are enriched from this client.
 */
@Service
public class OrchestratorModelWindowClient {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorModelWindowClient.class);
    private static final long CACHE_TTL_MS = 30_000;

    /**
     * The three context windows the orchestrator reports per model, any of
     * which may be {@code null} when unknown.
     *
     * @param min       smallest window currently served anywhere. A request may
     *                  land on any worker, so this is the only figure that
     *                  holds without further routing.
     * @param best      largest window currently served anywhere — reachable
     *                  when the request is routed to that worker.
     * @param nativeMax the model's own context length, i.e. what a lane serves
     *                  once it gets the KV cache it asks for. Known even for
     *                  models with no live lane, and the ceiling {@code best}
     *                  can grow to.
     */
    public record ModelContextWindows(Integer min, Integer best, Integer nativeMax) {
    }

    private final RestTemplate restTemplate;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    private volatile Map<String, ModelContextWindows> cached = Map.of();
    private volatile long cachedAtMs = 0;

    public OrchestratorModelWindowClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * Context windows keyed by model name. Returns the last cached result
     * (possibly empty) when the orchestrator is unreachable, so model listings
     * never fail on enrichment.
     */
    public Map<String, ModelContextWindows> getContextWindows() {
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
            Map<String, Object> body = response.getBody();
            Map<String, ModelContextWindows> windows = parseStats(body != null ? body.get("stats") : null);
            if (windows.isEmpty()) {
                // Orchestrator predates the "stats" field: fall back to the
                // flat model -> smallest-window map it has always sent.
                windows = parseFlatWindows(body != null ? body.get("windows") : null);
            }
            cached = windows;
        } catch (Exception e) {
            log.warn("Failed to fetch model context windows from orchestrator: {}", e.getMessage());
        }
        cachedAtMs = now;
        return cached;
    }

    private static Map<String, ModelContextWindows> parseStats(Object raw) {
        Map<String, ModelContextWindows> windows = new LinkedHashMap<>();
        if (!(raw instanceof Map<?, ?> byModel)) {
            return windows;
        }
        for (Map.Entry<?, ?> entry : byModel.entrySet()) {
            if (!(entry.getKey() instanceof String model) || !(entry.getValue() instanceof Map<?, ?> fields)) {
                continue;
            }
            ModelContextWindows parsed = new ModelContextWindows(
                positiveInt(fields.get("min")),
                positiveInt(fields.get("best")),
                positiveInt(fields.get("native")));
            if (parsed.min() != null || parsed.best() != null || parsed.nativeMax() != null) {
                windows.put(model, parsed);
            }
        }
        return windows;
    }

    private static Map<String, ModelContextWindows> parseFlatWindows(Object raw) {
        Map<String, ModelContextWindows> windows = new LinkedHashMap<>();
        if (!(raw instanceof Map<?, ?> byModel)) {
            return windows;
        }
        for (Map.Entry<?, ?> entry : byModel.entrySet()) {
            if (entry.getKey() instanceof String model) {
                Integer window = positiveInt(entry.getValue());
                if (window != null) {
                    windows.put(model, new ModelContextWindows(window, null, null));
                }
            }
        }
        return windows;
    }

    private static Integer positiveInt(Object value) {
        if (value instanceof Number number && number.intValue() > 0) {
            return number.intValue();
        }
        return null;
    }
}
