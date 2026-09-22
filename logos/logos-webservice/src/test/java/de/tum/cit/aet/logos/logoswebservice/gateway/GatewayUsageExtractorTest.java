package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.charset.StandardCharsets;
import java.util.Map;

import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * The canonical vocabulary here is what {@code logos_price_usage} reads by
 * name, so a mapping that drifts silently bills a cache read or a reasoning
 * token at the base rate.
 */
class GatewayUsageExtractorTest {

    private final ObjectMapper mapper = new ObjectMapper();

    private Map<String, Long> fromJson(String json) {
        return GatewayUsageExtractor.fromJsonBody(mapper, json.getBytes(StandardCharsets.UTF_8));
    }

    @Test
    void chatCompletionsUsage_mapsOntoCanonicalNames() {
        Map<String, Long> usage = fromJson("""
            {"id":"chatcmpl-1","usage":{
               "prompt_tokens":1000,"completion_tokens":300,"total_tokens":1300}}
            """);

        assertThat(usage).containsExactlyInAnyOrderEntriesOf(Map.of(
            "prompt_tokens", 1000L,
            "completion_tokens", 300L,
            "total_tokens", 1300L));
    }

    @Test
    void chatCompletionsDetails_flattenOntoCacheAndReasoningNames() {
        Map<String, Long> usage = fromJson("""
            {"usage":{
               "prompt_tokens":1000,"completion_tokens":300,
               "prompt_tokens_details":{"cached_tokens":800,"audio_tokens":20},
               "completion_tokens_details":{"reasoning_tokens":150}}}
            """);

        assertThat(usage)
            .containsEntry("prompt_cached_tokens", 800L)
            .containsEntry("prompt_audio_tokens", 20L)
            .containsEntry("completion_reasoning_tokens", 150L);
    }

    @Test
    void responsesApiUsage_rendersAsPromptAndCompletion() {
        Map<String, Long> usage = fromJson("""
            {"usage":{
               "input_tokens":500,"output_tokens":120,"total_tokens":620,
               "input_tokens_details":{"cached_tokens":400},
               "output_tokens_details":{"reasoning_tokens":60}}}
            """);

        assertThat(usage).containsExactlyInAnyOrderEntriesOf(Map.of(
            "prompt_tokens", 500L,
            "completion_tokens", 120L,
            "total_tokens", 620L,
            "prompt_cached_tokens", 400L,
            "completion_reasoning_tokens", 60L));
    }

    @Test
    void responsesApiEvent_readsUsageOffTheNestedResponse() {
        Map<String, Long> usage = fromJson("""
            {"type":"response.completed",
             "response":{"id":"resp-1","usage":{"input_tokens":70,"output_tokens":9}}}
            """);

        assertThat(usage).containsExactlyInAnyOrderEntriesOf(Map.of(
            "prompt_tokens", 70L, "completion_tokens", 9L));
    }

    @Test
    void deepSeekCacheHitSpelling_mapsOntoCachedTokens() {
        assertThat(fromJson("""
            {"usage":{"prompt_tokens":900,"prompt_cache_hit_tokens":700,
                      "prompt_cache_miss_tokens":200}}
            """))
            .containsEntry("prompt_cached_tokens", 700L)
            .containsEntry("prompt_cache_miss_tokens", 200L);
    }

    @Test
    void zeroAndNegativeCountsAreNotStored() {
        // usage_tokens holds billable quantities only — a zero row would price
        // as nothing but still claim the request was metered.
        assertThat(fromJson("""
            {"usage":{"prompt_tokens":0,"completion_tokens":-5,"total_tokens":10}}
            """))
            .containsExactlyInAnyOrderEntriesOf(Map.of("total_tokens", 10L));
    }

    @Test
    void nonTokenDiagnosticsAreDropped() {
        // These sit inside `usage` on some upstreams; billing them as tokens
        // would charge a duration as a token count.
        assertThat(fromJson("""
            {"usage":{"prompt_tokens":10,"total_duration":123456,"eval_count":7,
                      "response_token/s":31.5,"billed_requests":99}}
            """))
            .containsExactlyInAnyOrderEntriesOf(Map.of("prompt_tokens", 10L));
    }

    @Test
    void bodyWithoutUsageYieldsNothing() {
        assertThat(fromJson("{\"id\":\"chatcmpl-1\",\"choices\":[]}")).isEmpty();
        assertThat(fromJson("not json at all")).isEmpty();
        assertThat(GatewayUsageExtractor.fromJsonBody(mapper, new byte[0])).isEmpty();
    }

    @Test
    void sseDataLine_readsTerminalUsageChunk() {
        Map<String, Long> usage = GatewayUsageExtractor.fromSseDataLine(mapper,
            "data: {\"choices\":[],\"usage\":{\"prompt_tokens\":42,\"completion_tokens\":8}}");

        assertThat(usage).containsExactlyInAnyOrderEntriesOf(Map.of(
            "prompt_tokens", 42L, "completion_tokens", 8L));
    }

    @Test
    void sseTerminatorsAndContentChunksCarryNoUsage() {
        assertThat(GatewayUsageExtractor.fromSseDataLine(mapper, "data: [DONE]")).isEmpty();
        assertThat(GatewayUsageExtractor.fromSseDataLine(mapper,
            "data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}")).isEmpty();
        assertThat(GatewayUsageExtractor.fromSseDataLine(mapper, ": keep-alive")).isEmpty();
        assertThat(GatewayUsageExtractor.fromSseDataLine(mapper, "")).isEmpty();
    }
}
