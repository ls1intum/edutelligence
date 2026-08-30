package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Consumer;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;

/**
 * Token counts of the requests streaming right now, from the orchestrator.
 *
 * A finished request's usage is in the database. One still running is only in
 * the orchestrator, which is the process the chunks pass through — so the
 * request feed showed a row with no numbers for the whole minute a long
 * generation takes, then filled it in at once when the request ended.
 *
 * The primary transport is the orchestrator's SSE stream: a token delta is on
 * the wire a couple of hundred milliseconds after it happens, and every data
 * line updates the cached snapshot and notifies the listener, which is what
 * lets the websocket handler push its viewers without waiting for the next
 * tick. The one-shot GET stays as the fallback: when the subscription is
 * down — or the snapshot is stale, which is how a dead connection reveals
 * itself — a pull fetches what a push did not deliver.
 */
@Service
public class OrchestratorLiveStreamClient {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorLiveStreamClient.class);

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /**
     * A cached snapshot younger than this is served without a pull. Older than
     * this and the SSE connection is presumed dead (the orchestrator pings it
     * far more often), so the next read falls back to the one-shot GET.
     */
    private static final long STALE_AFTER_MS = 5_000;

    private static final long RECONNECT_INITIAL_MS = 1_000;
    private static final long RECONNECT_MAX_MS = 30_000;

    /**
     * One in-flight request.
     *
     * @param promptTokens     exact as soon as the stream opened, but an
     *                         estimate while the request still queues: until
     *                         the upstream states the prompt size, this is the
     *                         figure context routing computed from the body
     * @param completionTokens the count so far. Approximate while the request
     *                         runs: the settled figure only arrives with the
     *                         terminal usage event, so until then the
     *                         orchestrator counts text deltas. Replaced by the
     *                         real number the moment the request completes, and
     *                         never stored or billed from.
     * @param tokensPerSecond  measured from the first token rather than from
     *                         arrival, so queueing does not drag it down. Null
     *                         until there is a span to divide by.
     * @param promptEstimated  true while promptTokens is that estimate, so the
     *                         page can show it as such.
     */
    public record LiveStream(int promptTokens, int completionTokens, Double tokensPerSecond, boolean promptEstimated) {
    }

    private record Snapshot(Map<String, LiveStream> streams, long receivedAtMs) {
    }

    private final RestTemplate restTemplate;
    private final HttpClient http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(3))
        .build();

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    /** The last snapshot the SSE stream delivered, no matter how old. */
    private final AtomicReference<Snapshot> cached = new AtomicReference<>();
    /** Called on the SSE thread whenever a new snapshot arrives. */
    private final AtomicReference<Consumer<Map<String, LiveStream>>> onLiveUpdate = new AtomicReference<>();
    private volatile Thread sseThread;

    public OrchestratorLiveStreamClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @PostConstruct
    void start() {
        if (orchestratorUrl.isBlank() || internalSecret.isBlank()) return;
        sseThread = new Thread(this::runSseLoop, "orchestrator-live-streams");
        sseThread.setDaemon(true);
        sseThread.start();
    }

    @PreDestroy
    void stop() {
        Thread thread = sseThread;
        if (thread != null) thread.interrupt();
    }

    /**
     * In-flight requests keyed by request id. Empty when the orchestrator is
     * unreachable or not configured — the feed then shows what the database
     * holds, which is what it did before any of this existed.
     */
    public Map<String, LiveStream> getLiveStreams() {
        if (orchestratorUrl.isBlank() || internalSecret.isBlank()) {
            return Map.of();
        }
        Snapshot snapshot = cached.get();
        if (snapshot != null && System.currentTimeMillis() - snapshot.receivedAtMs() < STALE_AFTER_MS) {
            return snapshot.streams();
        }
        // Stale or never received: pull. The pull doubles as the liveness
        // check for the push — a subscription whose last line is older than
        // STALE_AFTER_MS has died silently, and this call is what notices.
        return fetchLiveStreams();
    }

    /**
     * Called by the websocket handler to push a fresh snapshot to its viewers
     * the moment it arrives, instead of waiting for the next tick.
     */
    public void setOnLiveUpdate(Consumer<Map<String, LiveStream>> listener) {
        onLiveUpdate.set(listener);
    }

    private Map<String, LiveStream> fetchLiveStreams() {
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("Authorization", "Bearer " + internalSecret);
            var response = restTemplate.exchange(
                orchestratorUrl + "/internal/live_streams",
                HttpMethod.GET,
                new HttpEntity<Void>(headers),
                Map.class);
            Map<String, Object> body = response.getBody();
            Map<String, LiveStream> streams = parseStreams(body != null ? body.get("streams") : null);
            if (!streams.isEmpty()) {
                cached.set(new Snapshot(streams, System.currentTimeMillis()));
            }
            return streams;
        } catch (Exception e) {
            log.debug("Failed to fetch live streams from orchestrator: {}", e.getMessage());
            return Map.of();
        }
    }

    /**
     * One lap around the SSE connection: block on its lines until it ends,
     * then reconnect with a backoff that resets on a connection that lasted.
     */
    private void runSseLoop() {
        long backoffMs = RECONNECT_INITIAL_MS;
        while (!Thread.currentThread().isInterrupted()) {
            long connectedAt = System.currentTimeMillis();
            try {
                HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(orchestratorUrl + "/internal/live_streams/stream"))
                    .header("Authorization", "Bearer " + internalSecret)
                    .header("Accept", "text/event-stream")
                    .GET()
                    .build();
                HttpResponse<java.util.stream.Stream<String>> response =
                    http.send(request, HttpResponse.BodyHandlers.ofLines());
                if (response.statusCode() != 200) {
                    throw new IllegalStateException("live stream endpoint returned " + response.statusCode());
                }
                try (var lines = response.body()) {
                    var it = lines.iterator();
                    while (it.hasNext()) {
                        handleLine(it.next());
                    }
                }
                backoffMs = RECONNECT_INITIAL_MS;  // ran down, not down
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            } catch (Exception e) {
                log.debug("Live stream connection ended: {}", e.getMessage());
                // A connection that lasted a while just dropped (an orchestrator
                // restart): reconnect promptly. Only repeated immediate
                // failures earn the growing backoff.
                if (System.currentTimeMillis() - connectedAt >= RECONNECT_MAX_MS) {
                    backoffMs = RECONNECT_INITIAL_MS;
                }
            }
            if (Thread.currentThread().isInterrupted()) return;
            try {
                Thread.sleep(backoffMs);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
            backoffMs = Math.min(backoffMs * 2, RECONNECT_MAX_MS);
        }
    }

    /**
     * One line of the SSE stream. A data line is a full snapshot (the same
     * shape the GET serves); a comment line is the orchestrator's heartbeat —
     * nothing changed, but the connection is alive, which is worth knowing.
     */
    public void handleLine(String line) {
        if (line.startsWith("data: ")) {
            try {
                Map<String, Object> body = MAPPER.readValue(line.substring(6), new TypeReference<>() {});
                Map<String, LiveStream> streams = parseStreams(body.get("streams"));
                cached.set(new Snapshot(streams, System.currentTimeMillis()));
                Consumer<Map<String, LiveStream>> listener = onLiveUpdate.get();
                if (listener != null) listener.accept(streams);
            } catch (Exception e) {
                log.debug("Failed to parse live stream event: {}", e.getMessage());
            }
        } else if (line.startsWith(":")) {
            cached.updateAndGet(s -> s == null ? null : new Snapshot(s.streams(), System.currentTimeMillis()));
        }
    }

    private static Map<String, LiveStream> parseStreams(Object raw) {
        if (!(raw instanceof List<?> rows)) return Map.of();
        Map<String, LiveStream> streams = new LinkedHashMap<>();
        for (Object row : rows) {
            if (!(row instanceof Map<?, ?> fields)) continue;
            if (!(fields.get("request_id") instanceof String requestId) || requestId.isBlank()) continue;
            streams.put(requestId, new LiveStream(
                intOf(fields.get("prompt_tokens")),
                intOf(fields.get("completion_tokens")),
                fields.get("tokens_per_second") instanceof Number n ? n.doubleValue() : null,
                Boolean.TRUE.equals(fields.get("prompt_estimated"))));
        }
        return streams;
    }

    private static int intOf(Object value) {
        return value instanceof Number number ? number.intValue() : 0;
    }
}
