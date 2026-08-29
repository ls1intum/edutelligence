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
 * Token counts of the requests streaming right now, from the orchestrator.
 *
 * A finished request's usage is in the database. One still running is only in
 * the orchestrator, which is the process the chunks pass through — so the
 * request feed showed a row with no numbers for the whole minute a long
 * generation takes, then filled it in at once when the request ended.
 *
 * Deliberately not cached: the point of these figures is that they move. The
 * call is a dict lookup on the far end with no database work behind it, and it
 * runs on the cadence the feed is already pushed at.
 */
@Service
public class OrchestratorLiveStreamClient {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorLiveStreamClient.class);

    /**
     * One in-flight request.
     *
     * @param promptTokens     exact — every API states the prompt size up front
     * @param completionTokens the count so far. Approximate while the request
     *                         runs: the settled figure only arrives with the
     *                         terminal usage event, so until then the
     *                         orchestrator counts text deltas. Replaced by the
     *                         real number the moment the request completes, and
     *                         never stored or billed from.
     * @param tokensPerSecond  measured from the first token rather than from
     *                         arrival, so queueing does not drag it down. Null
     *                         until there is a span to divide by.
     */
    public record LiveStream(int promptTokens, int completionTokens, Double tokensPerSecond) {
    }

    private final RestTemplate restTemplate;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    public OrchestratorLiveStreamClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * In-flight requests keyed by request id. Empty when the orchestrator is
     * unreachable or not configured — the feed then shows what the database
     * holds, which is what it did before any of this existed.
     */
    @SuppressWarnings("unchecked")
    public Map<String, LiveStream> getLiveStreams() {
        if (orchestratorUrl.isBlank() || internalSecret.isBlank()) {
            return Map.of();
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("Authorization", "Bearer " + internalSecret);
            var response = restTemplate.exchange(
                orchestratorUrl + "/internal/live_streams",
                HttpMethod.GET,
                new HttpEntity<Void>(headers),
                Map.class);
            Map<String, Object> body = response.getBody();
            Object raw = body != null ? body.get("streams") : null;
            if (!(raw instanceof List<?> rows)) {
                return Map.of();
            }
            Map<String, LiveStream> streams = new LinkedHashMap<>();
            for (Object row : rows) {
                if (!(row instanceof Map<?, ?> fields)) continue;
                if (!(fields.get("request_id") instanceof String requestId) || requestId.isBlank()) continue;
                streams.put(requestId, new LiveStream(
                    intOf(fields.get("prompt_tokens")),
                    intOf(fields.get("completion_tokens")),
                    fields.get("tokens_per_second") instanceof Number n ? n.doubleValue() : null));
            }
            return streams;
        } catch (Exception e) {
            log.debug("Failed to fetch live streams from orchestrator: {}", e.getMessage());
            return Map.of();
        }
    }

    private static int intOf(Object value) {
        return value instanceof Number number ? number.intValue() : 0;
    }
}
