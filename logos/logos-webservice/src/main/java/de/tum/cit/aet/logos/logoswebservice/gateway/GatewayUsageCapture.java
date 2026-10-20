package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Map;
import java.util.function.Supplier;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Sniffs the token usage and the service tier out of a cloud response while it
 * streams to the client.
 *
 * <p>The client's bytes are never delayed or altered: every write passes
 * straight through to the delegate and the copy is what gets inspected. Two
 * shapes matter, and each is bounded so a large response cannot grow the heap
 * with the body it is forwarding:
 *
 * <ul>
 *   <li><b>SSE</b> — only the current line is buffered. Each {@code data:} line
 *       is parsed as it completes and the last usage seen wins, which is the
 *       terminal {@code stream_options.include_usage} chunk (Chat Completions)
 *       or the {@code response.completed} event (Responses API).</li>
 *   <li><b>JSON</b> — buffered up to {@link #JSON_CAPTURE_LIMIT_BYTES} and
 *       parsed once the stream closes. A body past the cap yields no usage
 *       rather than a truncated parse.</li>
 * </ul>
 *
 * <p>With {@code retainBody} the JSON buffer is kept after parsing so a key
 * configured for full request logging can store the response. It stays off
 * otherwise, so a body no one will read is dropped as soon as its usage is out.
 */
final class GatewayUsageCapture extends OutputStream {

    /**
     * A chat completion carrying usage is far below this; the cap only exists
     * so an unexpectedly large non-streaming body (a long embeddings batch)
     * cannot be mirrored in full.
     */
    static final int JSON_CAPTURE_LIMIT_BYTES = 1024 * 1024;

    /** One SSE event that exceeds this is skipped rather than buffered. */
    static final int SSE_LINE_LIMIT_BYTES = 256 * 1024;

    private final OutputStream delegate;
    private final ObjectMapper objectMapper;
    private final boolean sse;
    private final boolean retainBody;
    private final Supplier<Instant> clock;

    private final ByteArrayOutputStream buffer = new ByteArrayOutputStream();
    private boolean bufferOverflowed;
    private Map<String, Long> usage = Map.of();
    private String serviceTier;
    private byte[] capturedBody;
    private Instant firstByteAt;
    private Instant firstTokenAt;
    /** When the chunk being written arrived, before it was passed to the client. */
    private Instant chunkArrivedAt;

    GatewayUsageCapture(OutputStream delegate, ObjectMapper objectMapper, String upstreamContentType) {
        this(delegate, objectMapper, upstreamContentType, false, Instant::now);
    }

    /**
     * @param clock dates the arrival of each chunk; the forwarder passes the
     *              instant its reader took the chunk from the upstream, so a
     *              slow client does not shift it
     */
    GatewayUsageCapture(OutputStream delegate, ObjectMapper objectMapper,
                        String upstreamContentType, boolean retainBody, Supplier<Instant> clock) {
        this.delegate = delegate;
        this.clock = clock;
        this.objectMapper = objectMapper;
        this.sse = isEventStream(upstreamContentType);
        this.retainBody = retainBody;
    }

    static boolean isEventStream(String contentType) {
        return contentType != null
            && contentType.toLowerCase(java.util.Locale.ROOT).contains("text/event-stream");
    }

    /**
     * When the first response body byte arrived from the upstream; null while
     * none has. For a stream this can be a role-only event or a keep-alive.
     */
    Instant firstByteAt() {
        return firstByteAt;
    }

    /**
     * When the first token arrived from the upstream; null while none has.
     *
     * <p>For a stream it is the first event that carries generated content
     * (see {@link #carriesContent}), not the first byte: a stream often opens
     * with a role-only delta or a keep-alive, which would understate the time
     * to the first token. A stream in which no event is recognised as content
     * (an unfamiliar event format) falls back to the first byte, so the figure
     * stays available. A JSON body has no tokens in flight; its first byte is
     * the moment the whole answer starts to arrive and stands in for it.
     */
    Instant firstTokenAt() {
        return firstTokenAt != null ? firstTokenAt : firstByteAt;
    }

    /** The usage seen so far; empty when the response carried none. */
    Map<String, Long> usage() {
        return usage;
    }

    /** The service tier the response reported, lowercased; null when it reported none. */
    String serviceTier() {
        return serviceTier;
    }

    /**
     * The response body, when it was retained and fits the cap. Null for a
     * stream, which has no single body, and whenever retention is off.
     */
    byte[] capturedBody() {
        return capturedBody;
    }

    @Override
    public void write(int b) throws IOException {
        chunkArrivedAt = clock.get();
        markFirstByte(1);
        delegate.write(b);
        capture(new byte[] {(byte) b}, 0, 1);
    }

    @Override
    public void write(byte[] b, int off, int len) throws IOException {
        // Overridden so the pass-through stays a bulk copy: FilterOutputStream's
        // default would forward this byte by byte.
        // Taken before the write: a slow client must not delay the instant
        // this chunk is recorded as having arrived from the upstream.
        chunkArrivedAt = clock.get();
        markFirstByte(len);
        delegate.write(b, off, len);
        capture(b, off, len);
    }

    @Override
    public void flush() throws IOException {
        delegate.flush();
    }

    @Override
    public void close() throws IOException {
        try {
            if (!sse) {
                finishJson();
            } else {
                finishSseLine();
            }
        } finally {
            delegate.close();
        }
    }

    private void markFirstByte(int len) {
        if (firstByteAt == null && len > 0) {
            firstByteAt = chunkArrivedAt;
        }
    }

    private void capture(byte[] b, int off, int len) {
        if (len <= 0) {
            return;
        }
        if (sse) {
            captureSse(b, off, len);
        } else {
            captureJson(b, off, len);
        }
    }

    private void captureJson(byte[] b, int off, int len) {
        if (bufferOverflowed) {
            return;
        }
        if (buffer.size() + len > JSON_CAPTURE_LIMIT_BYTES) {
            bufferOverflowed = true;
            buffer.reset();
            return;
        }
        buffer.write(b, off, len);
    }

    private void captureSse(byte[] b, int off, int len) {
        for (int i = off; i < off + len; i++) {
            byte current = b[i];
            if (current == '\n') {
                finishSseLine();
                continue;
            }
            if (bufferOverflowed) {
                continue;
            }
            if (buffer.size() >= SSE_LINE_LIMIT_BYTES) {
                bufferOverflowed = true;
                buffer.reset();
                continue;
            }
            buffer.write(current);
        }
    }

    private void finishSseLine() {
        if (bufferOverflowed) {
            bufferOverflowed = false;
            buffer.reset();
            return;
        }
        if (buffer.size() == 0) {
            return;
        }
        String line = buffer.toString(StandardCharsets.UTF_8);
        buffer.reset();
        JsonNode event = GatewayUsageExtractor.parseSseDataLine(objectMapper, line);
        if (event == null) {
            return;
        }
        if (firstTokenAt == null && carriesContent(event)) {
            firstTokenAt = chunkArrivedAt;
        }
        Map<String, Long> found = GatewayUsageExtractor.fromEnvelope(event);
        if (!found.isEmpty()) {
            // Later events refine earlier ones (Responses API reports usage on
            // response.completed after incremental events).
            usage = found;
        }
        String tier = GatewayUsageExtractor.serviceTier(event);
        if (tier != null) {
            serviceTier = tier;
        }
    }

    /**
     * Whether a streamed event carries generated content: a non-empty text,
     * reasoning or tool-call delta of a Chat Completions chunk, the text of a
     * legacy Completions chunk, a non-empty {@code *.delta} event of the
     * Responses API, or a {@code content_block_delta} of the Messages API.
     * Role-only deltas, usage-only chunks and lifecycle events are not.
     */
    static boolean carriesContent(JsonNode event) {
        JsonNode choices = event.path("choices");
        if (choices.isArray()) {
            for (JsonNode choice : choices) {
                JsonNode delta = choice.path("delta");
                if (nonEmptyText(delta.path("content")) || nonEmptyText(delta.path("reasoning_content"))
                        || nonEmptyText(delta.path("reasoning")) || nonEmptyText(choice.path("text"))
                        || (delta.path("tool_calls").isArray() && !delta.path("tool_calls").isEmpty())) {
                    return true;
                }
            }
        }
        String type = event.path("type").asText("");
        if (type.endsWith(".delta") && nonEmptyText(event.path("delta"))) {
            return true;
        }
        if ("content_block_delta".equals(type)) {
            JsonNode delta = event.path("delta");
            return nonEmptyText(delta.path("text")) || nonEmptyText(delta.path("thinking"))
                || nonEmptyText(delta.path("partial_json"));
        }
        return false;
    }

    private static boolean nonEmptyText(JsonNode node) {
        if (node.isTextual()) {
            return !node.asText().isEmpty();
        }
        // Some providers send content as an array of parts.
        return node.isArray() && !node.isEmpty();
    }

    private void finishJson() {
        if (bufferOverflowed || buffer.size() == 0) {
            return;
        }
        byte[] body = buffer.toByteArray();
        buffer.reset();
        JsonNode root = GatewayUsageExtractor.parseJsonBody(objectMapper, body);
        if (root != null) {
            Map<String, Long> found = GatewayUsageExtractor.fromEnvelope(root);
            if (!found.isEmpty()) {
                usage = found;
            }
            serviceTier = GatewayUsageExtractor.serviceTier(root);
        }
        if (retainBody) {
            capturedBody = body;
        }
    }
}
