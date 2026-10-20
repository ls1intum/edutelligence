package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * Streams an authenticated request to a cloud upstream (JDK {@link HttpClient}).
 *
 * <p>Connection pool state in the shared {@link HttpClient} is the only process
 * state held here.
 */
@Service
public class GatewayCloudForwarder {

    /**
     * How long the upstream reader waits for the relay to start. A relay that
     * was rejected or cancelled before it ran never starts; the pump then
     * closes the upstream if {@link GatewayRelayCleanup} has not already.
     * Matches the default async request timeout, after which the relay is
     * gone anyway.
     */
    static final Duration RELAY_ATTACH_TIMEOUT = Duration.ofMinutes(30);

    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;

    public GatewayCloudForwarder(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        // HTTP/1.1 only: default h2c Upgrade breaks body delivery to some
        // upstreams (same failure mode as GatewayOrchestratorProxy).
        this.httpClient = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(10))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
    }

    /**
     * Forward to the chosen cloud deployment.
     *
     * @param inferencePath normalized path such as {@code /v1/chat/completions}
     * @param queryString   raw query string without leading {@code ?}, or null
     * @param method        HTTP method
     * @param body          request body bytes (may be empty)
     * @param inboundHeaders inbound request headers to selectively copy (Content-Type)
     * @param retainResponseBody keep the (non-streamed) response body for payload
     *                      logging; only set for a key that logs payloads
     * @param onSuccess     invoked once the body has been fully streamed, with the
     *                      response's canonical token usage and, when retained,
     *                      its body
     * @param onFailure     invoked when the upstream call or stream fails, with the
     *                      error and the instants the forward reached
     */
    public ResponseEntity<StreamingResponseBody> forward(
            GatewayDeployment deployment,
            String inferencePath,
            String queryString,
            String method,
            byte[] body,
            Map<String, List<String>> inboundHeaders,
            boolean retainResponseBody,
            java.util.function.Consumer<GatewayForwardResult> onSuccess,
            java.util.function.BiConsumer<String, GatewayForwardTimings> onFailure) throws IOException {

        String forwardUrl = CloudForwardUrlBuilder.build(
            deployment.baseUrl(), inferencePath, deployment.endpoint());

        Optional<CloudForwardUrlBuilder.AzureResponsesRewrite> responses =
            CloudForwardUrlBuilder.azureResponsesRewrite(forwardUrl);
        String azureDeploymentId = null;
        if (responses.isPresent()) {
            forwardUrl = responses.get().realUrl();
            azureDeploymentId = responses.get().deploymentId();
        }

        forwardUrl = GatewayQueryMerge.merge(forwardUrl, queryString);

        byte[] outboundBody = requestUsageOnStream(body, forwardUrl);
        if (azureDeploymentId != null && outboundBody != null && outboundBody.length > 0) {
            outboundBody = rewriteModelField(outboundBody, azureDeploymentId);
        }

        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(forwardUrl))
            .timeout(Duration.ofMinutes(10));

        String contentType = firstHeader(inboundHeaders, "content-type");
        if (contentType != null) {
            builder.header("Content-Type", contentType);
        } else if (outboundBody != null && outboundBody.length > 0) {
            builder.header("Content-Type", "application/json");
        }

        CloudAuthHeaders.authHeader(
                deployment.authName(),
                deployment.authFormat(),
                deployment.apiKey(),
                deployment.cloudProviderType())
            .ifPresent(h -> builder.header(h.name(), h.value()));

        for (Map.Entry<String, String> h : CloudAuthHeaders.protocolHeaders(deployment.cloudProviderType()).entrySet()) {
            builder.header(h.getKey(), h.getValue());
        }

        String accept = firstHeader(inboundHeaders, "accept");
        if (accept != null) {
            builder.header("Accept", accept);
        }

        HttpRequest.BodyPublisher publisher = (outboundBody == null || outboundBody.length == 0)
            ? HttpRequest.BodyPublishers.noBody()
            : HttpRequest.BodyPublishers.ofByteArray(outboundBody);
        builder.method(method.toUpperCase(Locale.ROOT), publisher);

        HttpResponse<InputStream> upstream;
        Instant providerCall = Instant.now();
        try {
            upstream = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofInputStream());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            if (onFailure != null) {
                onFailure.accept("Interrupted while forwarding to cloud",
                    new GatewayForwardTimings(providerCall, null, Instant.now()));
            }
            throw new IOException("Interrupted while forwarding to cloud", e);
        } catch (IOException e) {
            if (onFailure != null) {
                onFailure.accept(e.getMessage(), new GatewayForwardTimings(providerCall, null, Instant.now()));
            }
            throw e;
        }

        Instant headersAt = Instant.now();
        int status = upstream.statusCode();
        boolean upstreamOk = status >= 200 && status < 400;

        Set<String> exclude = GatewayHopByHop.responseExcludeNames(upstream.headers().map());
        HttpHeaders responseHeaders = new HttpHeaders();
        upstream.headers().map().forEach((name, values) -> {
            if (name == null || exclude.contains(name.toLowerCase(Locale.ROOT))) {
                return;
            }
            responseHeaders.put(name, values);
        });

        // A separate reader stamps each chunk as it arrives from the upstream,
        // so neither a client that is slow to take the bytes nor the wait for
        // an executor thread to run the relay shifts the provider's timestamps.
        // It starts here, not in the relay, for the second reason.
        UpstreamPump pump = UpstreamPump.start(upstream.body(), headersAt, RELAY_ATTACH_TIMEOUT);
        GatewayRelayCleanup.closeWhenRequestEnds(pump);
        String upstreamContentType = upstream.headers().firstValue("content-type").orElse(null);
        StreamingResponseBody stream = outputStream -> {
            IOException streamError = null;
            // The capture sits between the upstream and the client so the
            // reported token counts can be billed; it never delays or alters
            // the bytes the client receives.
            GatewayUsageCapture capture = new GatewayUsageCapture(
                outputStream, objectMapper, upstreamContentType, retainResponseBody, pump::currentChunkAt);
            try (pump; OutputStream out = capture) {
                pump.transferTo(out);
                out.flush();
            } catch (IOException e) {
                streamError = e;
            }
            GatewayForwardTimings timings = new GatewayForwardTimings(
                providerCall, capture.firstTokenAt(), pump.endedAt());
            if (streamError != null) {
                if (onFailure != null) {
                    onFailure.accept(streamError.getMessage(), timings);
                }
                throw streamError;
            }
            if (upstreamOk) {
                if (onSuccess != null) {
                    onSuccess.accept(new GatewayForwardResult(
                        capture.usage(), capture.capturedBody(), capture.serviceTier(), timings));
                }
            } else if (onFailure != null) {
                onFailure.accept("Upstream HTTP " + status, timings);
            }
        };

        return ResponseEntity.status(status).headers(responseHeaders)
            .body(GatewayRelayOccupancy.track(stream));
    }

    /**
     * Reads the upstream body on its own thread and stamps each chunk with the
     * instant it arrived.
     *
     * <p>Relaying on one thread would date every chunk read after a blocked
     * client write too late, and dating by read time alone would drop provider
     * work that overlapped such a write. The reader keeps taking bytes while
     * the client is slow, so the stamps follow the upstream. It buffers up to
     * {@link #MAX_CHUNKS} chunks; past that it waits for the client like a
     * direct relay would.
     *
     * <p>The reader starts before the relay runs. A relay that never starts
     * (rejected or cancelled before it ran) must not leave the reader and the
     * upstream connection behind: {@link GatewayRelayCleanup} closes the pump
     * when the request ends, and a watchdog closes it when no relay attached
     * within the attach timeout, whether or not the buffer is full.
     */
    static final class UpstreamPump implements AutoCloseable {

        static final int MAX_CHUNKS = 1024;
        private static final int CHUNK_BYTES = 8192;

        private record Chunk(byte[] bytes, Instant at, IOException error) {
        }

        private static final Chunk END = new Chunk(null, null, null);

        private final InputStream in;
        private final java.util.concurrent.BlockingQueue<Chunk> chunks =
            new java.util.concurrent.ArrayBlockingQueue<>(MAX_CHUNKS);
        private final Thread reader;
        private final Thread watchdog;
        private final java.util.concurrent.atomic.AtomicBoolean closed =
            new java.util.concurrent.atomic.AtomicBoolean();
        private volatile Instant endedAt;
        private volatile boolean attached;
        private Instant currentChunkAt;

        private UpstreamPump(InputStream in, Instant headersAt, Duration attachTimeout) {
            this.in = in;
            this.currentChunkAt = headersAt;
            this.endedAt = headersAt;
            this.reader = Thread.ofVirtual().name("gateway-upstream-reader").unstarted(this::pump);
            this.watchdog = Thread.ofVirtual().name("gateway-upstream-watchdog").unstarted(() -> {
                try {
                    Thread.sleep(attachTimeout);
                } catch (InterruptedException e) {
                    return;
                }
                if (!attached) {
                    close();
                }
            });
        }

        /**
         * Starts reading {@code in} at once. If no relay starts taking chunks
         * within {@code attachTimeout}, the pump closes the upstream and a late
         * relay fails.
         */
        static UpstreamPump start(InputStream in, Instant headersAt, Duration attachTimeout) {
            UpstreamPump pump = new UpstreamPump(in, headersAt, attachTimeout);
            pump.reader.start();
            pump.watchdog.start();
            return pump;
        }

        private void pump() {
            Chunk last = END;
            try {
                byte[] buf = new byte[CHUNK_BYTES];
                int n;
                while ((n = in.read(buf)) != -1) {
                    Instant at = Instant.now();
                    endedAt = at;
                    if (n > 0) {
                        chunks.put(new Chunk(java.util.Arrays.copyOf(buf, n), at, null));
                    }
                }
                endedAt = Instant.now();
            } catch (IOException e) {
                endedAt = Instant.now();
                last = new Chunk(null, null, e);
            } catch (InterruptedException e) {
                return;
            }
            if (!closed.get()) {
                try {
                    chunks.put(last);
                } catch (InterruptedException ignored) {
                    // Closed meanwhile; close() leaves its own end marker.
                }
            }
        }

        /** Relays every chunk to {@code out}, in order, until the upstream ends. */
        void transferTo(OutputStream out) throws IOException {
            attached = true;
            watchdog.interrupt();
            if (closed.get()) {
                throw new IOException("The upstream body was released before the relay started");
            }
            while (true) {
                Chunk chunk;
                try {
                    chunk = chunks.take();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    throw new java.io.InterruptedIOException("Relay interrupted");
                }
                if (chunk.error() != null) {
                    throw chunk.error();
                }
                if (chunk.bytes() == null) {
                    return;
                }
                currentChunkAt = chunk.at();
                out.write(chunk.bytes());
            }
        }

        /** When the chunk being relayed arrived from the upstream. */
        Instant currentChunkAt() {
            return currentChunkAt;
        }

        /** When the upstream body ended, or the last chunk so far arrived. */
        Instant endedAt() {
            return endedAt;
        }

        boolean isClosed() {
            return closed.get();
        }

        /** Stops the reader and releases the upstream; safe to call more than once. */
        @Override
        public void close() {
            if (!closed.compareAndSet(false, true)) {
                return;
            }
            watchdog.interrupt();
            reader.interrupt();
            chunks.clear();
            // A relay blocked on take() ends instead of waiting forever.
            chunks.offer(new Chunk(null, null, new IOException("The upstream body was released")));
            try {
                in.close();
            } catch (IOException ignored) {
                // Closing only releases the connection; nothing waits on it.
            }
        }
    }

    /**
     * Ask a streaming Chat Completions upstream to report usage.
     *
     * <p>A stream otherwise ends without any token counts, leaving the request
     * unbillable. This mirrors what the orchestrator sends on its own streaming
     * path, including passing the terminal usage chunk through to the client.
     *
     * <p>Only the Chat Completions surfaces take the parameter. Everything else
     * the direct-cloud path allows — the Responses API, images, audio,
     * embeddings — either reports usage by itself or rejects the parameter as
     * unknown, so those are named out rather than assumed compatible.
     */
    private byte[] requestUsageOnStream(byte[] body, String forwardUrl) throws IOException {
        if (body == null || body.length == 0 || !acceptsStreamOptions(forwardUrl)) {
            return body;
        }
        JsonNode root;
        try {
            root = objectMapper.readTree(body);
        } catch (IOException e) {
            // Not JSON (or not parseable): forward it untouched.
            return body;
        }
        if (!(root instanceof ObjectNode obj) || !obj.path("stream").asBoolean(false)) {
            return body;
        }
        ObjectNode streamOptions = obj.withObject("/stream_options");
        streamOptions.put("include_usage", true);
        return objectMapper.writeValueAsBytes(obj);
    }

    /** Whether this upstream surface accepts {@code stream_options}. */
    static boolean acceptsStreamOptions(String forwardUrl) {
        String path = (forwardUrl == null ? "" : forwardUrl).split("\\?", 2)[0];
        while (path.endsWith("/")) {
            path = path.substring(0, path.length() - 1);
        }
        return path.endsWith("/chat/completions") || path.endsWith("/completions");
    }

    private byte[] rewriteModelField(byte[] body, String deploymentId) throws IOException {
        JsonNode root = objectMapper.readTree(body);
        if (root instanceof ObjectNode obj) {
            obj.put("model", deploymentId);
            return objectMapper.writeValueAsBytes(obj);
        }
        return body;
    }

    private static String firstHeader(Map<String, List<String>> headers, String name) {
        if (headers == null) {
            return null;
        }
        for (Map.Entry<String, List<String>> e : headers.entrySet()) {
            if (e.getKey() != null && e.getKey().equalsIgnoreCase(name)
                && e.getValue() != null && !e.getValue().isEmpty()) {
                return e.getValue().get(0);
            }
        }
        return null;
    }
}
