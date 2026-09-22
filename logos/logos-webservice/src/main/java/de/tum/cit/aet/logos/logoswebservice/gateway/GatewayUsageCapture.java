package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Sniffs the token usage out of a cloud response while it streams to the client.
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

    private final ByteArrayOutputStream buffer = new ByteArrayOutputStream();
    private boolean bufferOverflowed;
    private Map<String, Long> usage = Map.of();

    GatewayUsageCapture(OutputStream delegate, ObjectMapper objectMapper, String upstreamContentType) {
        this.delegate = delegate;
        this.objectMapper = objectMapper;
        this.sse = isEventStream(upstreamContentType);
    }

    static boolean isEventStream(String contentType) {
        return contentType != null
            && contentType.toLowerCase(java.util.Locale.ROOT).contains("text/event-stream");
    }

    /** The usage seen so far; empty when the response carried none. */
    Map<String, Long> usage() {
        return usage;
    }

    @Override
    public void write(int b) throws IOException {
        delegate.write(b);
        capture(new byte[] {(byte) b}, 0, 1);
    }

    @Override
    public void write(byte[] b, int off, int len) throws IOException {
        // Overridden so the pass-through stays a bulk copy: FilterOutputStream's
        // default would forward this byte by byte.
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
        Map<String, Long> found = GatewayUsageExtractor.fromSseDataLine(objectMapper, line);
        if (!found.isEmpty()) {
            // Later events refine earlier ones (Responses API reports usage on
            // response.completed after incremental events).
            usage = found;
        }
    }

    private void finishJson() {
        if (bufferOverflowed || buffer.size() == 0) {
            return;
        }
        Map<String, Long> found = GatewayUsageExtractor.fromJsonBody(objectMapper, buffer.toByteArray());
        buffer.reset();
        if (!found.isEmpty()) {
            usage = found;
        }
    }
}
