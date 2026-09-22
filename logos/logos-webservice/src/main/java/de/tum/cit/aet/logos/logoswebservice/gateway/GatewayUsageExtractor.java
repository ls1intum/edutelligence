package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Normalises a cloud provider's {@code usage} block onto the canonical token
 * vocabulary that {@code usage_tokens} / {@code logos_price_usage} are keyed to.
 *
 * <p>The direct-cloud path bypasses the orchestrator, so the vocabulary the
 * orchestrator's {@code extract_token_usage} produces has to be reproduced
 * here — a name that does not match is priced at the base rate instead of its
 * own (cheaper) cache or reasoning rate.
 *
 * <p>Only the OpenAI-shaped surfaces are covered: {@link GatewayRouteResolver}
 * sends Anthropic-dialect deployments to the orchestrator, so Messages /
 * Bedrock Converse spellings cannot reach this class.
 */
final class GatewayUsageExtractor {

    /** Provider spellings of a canonical quantity. Values are never altered, only renamed. */
    private static final Map<String, String> KEY_MAP = Map.ofEntries(
        Map.entry("input_tokens", "prompt_tokens"),
        Map.entry("inputTokens", "prompt_tokens"),
        Map.entry("promptTokens", "prompt_tokens"),
        Map.entry("promptTokenCount", "prompt_tokens"),
        Map.entry("output_tokens", "completion_tokens"),
        Map.entry("outputTokens", "completion_tokens"),
        Map.entry("completionTokens", "completion_tokens"),
        Map.entry("candidatesTokenCount", "completion_tokens"),
        Map.entry("totalTokens", "total_tokens"),
        Map.entry("totalTokenCount", "total_tokens"),
        Map.entry("prompt_cache_hit_tokens", "prompt_cached_tokens"),
        Map.entry("promptCacheHitTokens", "prompt_cached_tokens"),
        Map.entry("promptCacheMissTokens", "prompt_cache_miss_tokens"),
        Map.entry("cache_read_input_tokens", "prompt_cached_tokens"),
        Map.entry("cache_creation_input_tokens", "prompt_cache_write_tokens"),
        Map.entry("cachedContentTokenCount", "prompt_cached_tokens"),
        Map.entry("thoughtsTokenCount", "completion_reasoning_tokens")
    );

    /** Nested {@code *_tokens_details} objects, flattened onto canonical names. */
    private static final Map<String, String> DETAILS_PREFIXES = Map.of(
        "prompt_tokens_details", "prompt_",
        "completion_tokens_details", "completion_",
        "input_tokens_details", "prompt_",
        "output_tokens_details", "completion_"
    );

    private static final Map<String, String> DETAIL_KEY_MAP = Map.of(
        "prompt_cached_tokens", "prompt_cached_tokens",
        "prompt_audio_tokens", "prompt_audio_tokens",
        "prompt_image_tokens", "prompt_image_tokens",
        "completion_audio_tokens", "completion_audio_tokens",
        "completion_image_tokens", "completion_image_tokens",
        "completion_reasoning_tokens", "completion_reasoning_tokens"
    );

    /**
     * Non-token diagnostics some providers report inside {@code usage}. Storing
     * them would price them as tokens at the base rate.
     */
    private static final java.util.Set<String> META_FIELDS = java.util.Set.of(
        "approximate_total", "eval_count", "eval_duration", "load_duration",
        "prompt_eval_count", "prompt_eval_duration", "total_duration"
    );

    private GatewayUsageExtractor() {
    }

    /**
     * Normalise one {@code usage} object.
     *
     * @return canonical name to count, only strictly positive integers, never null
     */
    static Map<String, Long> normalize(JsonNode usage) {
        Map<String, Long> out = new LinkedHashMap<>();
        if (usage == null || !usage.isObject()) {
            return out;
        }

        usage.fields().forEachRemaining(entry -> {
            String name = entry.getKey();
            if (name == null || DETAILS_PREFIXES.containsKey(name)) {
                return;
            }
            // ``billed_*`` is Logos's own derived-quantity namespace; a provider
            // emitting into it must not override a locally derived count.
            if (META_FIELDS.contains(name) || name.contains("/s") || name.startsWith("billed_")) {
                return;
            }
            put(out, KEY_MAP.getOrDefault(name, name), entry.getValue());
        });

        DETAILS_PREFIXES.forEach((detailsKey, prefix) -> {
            JsonNode details = usage.get(detailsKey);
            if (details == null || !details.isObject()) {
                return;
            }
            details.fields().forEachRemaining(entry -> {
                String flattened = prefix + entry.getKey();
                put(out, DETAIL_KEY_MAP.getOrDefault(flattened, flattened), entry.getValue());
            });
        });

        return out;
    }

    private static void put(Map<String, Long> out, String key, JsonNode value) {
        if (value == null || !value.isIntegralNumber()) {
            return;
        }
        long count = value.asLong();
        if (count <= 0) {
            // Only strictly positive counts are billable — the same invariant
            // the orchestrator's usage upsert enforces.
            return;
        }
        // A details block repeats a quantity the top level already reported;
        // the larger of the two is the inclusive one pricing expects.
        out.merge(key, count, Math::max);
    }

    /**
     * Pull usage out of a non-streaming JSON response body.
     *
     * <p>Chat Completions puts it at the top level; the Responses API nests it
     * under {@code response} when the body is an event envelope.
     */
    static Map<String, Long> fromJsonBody(ObjectMapper mapper, byte[] body) {
        if (body == null || body.length == 0) {
            return Map.of();
        }
        try {
            return fromEnvelope(mapper.readTree(body));
        } catch (Exception e) {
            // A body that is not JSON (or was truncated by the capture cap)
            // simply yields no usage; the caller falls back to the reservation.
            return Map.of();
        }
    }

    /**
     * Pull usage out of one parsed JSON value, whether it is the response
     * itself or a streaming event wrapping one.
     */
    static Map<String, Long> fromEnvelope(JsonNode root) {
        if (root == null || !root.isObject()) {
            return Map.of();
        }
        Map<String, Long> direct = normalize(root.get("usage"));
        if (!direct.isEmpty()) {
            return direct;
        }
        JsonNode response = root.get("response");
        if (response != null && response.isObject()) {
            return normalize(response.get("usage"));
        }
        return Map.of();
    }

    /**
     * Pull usage out of one SSE {@code data:} line.
     *
     * @return the usage of that event, or empty when the line carries none
     */
    static Map<String, Long> fromSseDataLine(ObjectMapper mapper, String line) {
        if (line == null) {
            return Map.of();
        }
        String trimmed = line.strip();
        if (!trimmed.startsWith("data:")) {
            return Map.of();
        }
        String payload = trimmed.substring("data:".length()).strip();
        if (payload.isEmpty() || "[DONE]".equals(payload)) {
            return Map.of();
        }
        try {
            return fromEnvelope(mapper.readTree(payload.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            return Map.of();
        }
    }
}
