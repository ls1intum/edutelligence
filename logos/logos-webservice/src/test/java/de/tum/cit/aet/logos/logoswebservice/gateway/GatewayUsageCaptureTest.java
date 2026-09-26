package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;

import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * The capture sits in the client's response path, so the bytes it forwards
 * must stay byte-identical no matter what it manages to parse out of them.
 */
class GatewayUsageCaptureTest {

    private final ObjectMapper mapper = new ObjectMapper();

    private static final String SSE = "text/event-stream; charset=utf-8";

    /** Feed the payload through in fixed-size pieces, as a network read would. */
    private Result stream(String contentType, String payload, int chunkSize) throws IOException {
        ByteArrayOutputStream sink = new ByteArrayOutputStream();
        byte[] bytes = payload.getBytes(StandardCharsets.UTF_8);
        GatewayUsageCapture capture = new GatewayUsageCapture(sink, mapper, contentType);
        for (int i = 0; i < bytes.length; i += chunkSize) {
            capture.write(bytes, i, Math.min(chunkSize, bytes.length - i));
        }
        capture.close();
        return new Result(capture.usage(), sink.toString(StandardCharsets.UTF_8));
    }

    private record Result(Map<String, Long> usage, String forwarded) {
    }

    @Test
    void jsonResponse_isForwardedVerbatimAndPriced() throws IOException {
        String body = """
            {"id":"chatcmpl-1","choices":[{"message":{"content":"hello"}}],
             "usage":{"prompt_tokens":120,"completion_tokens":30}}""";

        Result result = stream("application/json", body, 8);

        assertThat(result.forwarded()).isEqualTo(body);
        assertThat(result.usage()).containsExactlyInAnyOrderEntriesOf(Map.of(
            "prompt_tokens", 120L, "completion_tokens", 30L));
    }

    @Test
    void sseStream_readsTheTerminalUsageChunk() throws IOException {
        String body = """
            data: {"choices":[{"delta":{"content":"he"}}]}

            data: {"choices":[{"delta":{"content":"llo"}}]}

            data: {"choices":[],"usage":{"prompt_tokens":42,"completion_tokens":8}}

            data: [DONE]

            """;

        Result result = stream(SSE, body, 7);

        assertThat(result.forwarded()).isEqualTo(body);
        assertThat(result.usage()).containsExactlyInAnyOrderEntriesOf(Map.of(
            "prompt_tokens", 42L, "completion_tokens", 8L));
    }

    @Test
    void sseUsageSplitAcrossChunkBoundaries_isStillRead() throws IOException {
        // Network chunk boundaries do not line up with SSE event boundaries;
        // a per-chunk parse would lose the usage event entirely.
        String body = "data: {\"choices\":[],\"usage\":{\"prompt_tokens\":7,\"completion_tokens\":3}}\n\n";

        assertThat(stream(SSE, body, 1).usage())
            .containsExactlyInAnyOrderEntriesOf(Map.of("prompt_tokens", 7L, "completion_tokens", 3L));
    }

    @Test
    void sseWithCrLfAndNoTrailingNewline_isStillRead() throws IOException {
        String body = "data: {\"usage\":{\"prompt_tokens\":5}}\r\n\r\n"
            + "data: {\"usage\":{\"prompt_tokens\":5,\"completion_tokens\":2}}";

        Result result = stream(SSE, body, 16);

        assertThat(result.forwarded()).isEqualTo(body);
        assertThat(result.usage())
            .containsExactlyInAnyOrderEntriesOf(Map.of("prompt_tokens", 5L, "completion_tokens", 2L));
    }

    @Test
    void responsesApiStream_takesUsageFromTheCompletedEvent() throws IOException {
        String body = """
            event: response.output_text.delta
            data: {"type":"response.output_text.delta","delta":"hi"}

            event: response.completed
            data: {"type":"response.completed","response":{"usage":{"input_tokens":64,"output_tokens":12}}}

            """;

        assertThat(stream(SSE, body, 13).usage())
            .containsExactlyInAnyOrderEntriesOf(Map.of("prompt_tokens", 64L, "completion_tokens", 12L));
    }

    @Test
    void streamWithoutUsage_forwardsEverythingAndReportsNone() throws IOException {
        String body = """
            data: {"choices":[{"delta":{"content":"hello"}}]}

            data: [DONE]

            """;

        Result result = stream(SSE, body, 9);

        assertThat(result.forwarded()).isEqualTo(body);
        assertThat(result.usage()).isEmpty();
    }

    @Test
    void jsonBodyPastTheCaptureCap_isForwardedWholeButNotParsed() throws IOException {
        // The cap bounds the mirror, never the response: the client still gets
        // every byte, the request simply falls back to the flat reservation.
        String filler = "x".repeat(GatewayUsageCapture.JSON_CAPTURE_LIMIT_BYTES + 1024);
        String body = "{\"pad\":\"" + filler + "\",\"usage\":{\"prompt_tokens\":10}}";

        Result result = stream("application/json", body, 64 * 1024);

        assertThat(result.forwarded()).isEqualTo(body);
        assertThat(result.usage()).isEmpty();
    }

    @Test
    void oversizedSseEvent_isSkippedWithoutLosingLaterUsage() throws IOException {
        String huge = "data: {\"pad\":\"" + "y".repeat(GatewayUsageCapture.SSE_LINE_LIMIT_BYTES) + "\"}\n";
        String body = huge + "data: {\"usage\":{\"prompt_tokens\":11,\"completion_tokens\":4}}\n\n";

        Result result = stream(SSE, body, 32 * 1024);

        assertThat(result.forwarded()).isEqualTo(body);
        assertThat(result.usage())
            .containsExactlyInAnyOrderEntriesOf(Map.of("prompt_tokens", 11L, "completion_tokens", 4L));
    }

    @Test
    void singleByteWritesAreCapturedToo() throws IOException {
        ByteArrayOutputStream sink = new ByteArrayOutputStream();
        String body = "{\"usage\":{\"prompt_tokens\":3}}";
        GatewayUsageCapture capture = new GatewayUsageCapture(sink, mapper, "application/json");
        for (byte b : body.getBytes(StandardCharsets.UTF_8)) {
            capture.write(b);
        }
        capture.close();

        assertThat(sink.toString(StandardCharsets.UTF_8)).isEqualTo(body);
        assertThat(capture.usage()).containsExactlyInAnyOrderEntriesOf(Map.of("prompt_tokens", 3L));
    }

    @Test
    void contentTypeDecidesTheParseMode() {
        assertThat(GatewayUsageCapture.isEventStream("text/event-stream")).isTrue();
        assertThat(GatewayUsageCapture.isEventStream("TEXT/EVENT-STREAM; charset=utf-8")).isTrue();
        assertThat(GatewayUsageCapture.isEventStream("application/json")).isFalse();
        assertThat(GatewayUsageCapture.isEventStream(null)).isFalse();
    }
}
