package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.Locale;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * The reasoning effort a request body asks for, as stored on its
 * {@code log_entry} row.
 *
 * <p>The direct-cloud path forwards the body unchanged, so the effort in it is
 * the one the provider is sent. Each API surface keeps it elsewhere; the first
 * non-blank of these wins:
 * <ul>
 *   <li>{@code reasoning_effort} (OpenAI Chat Completions, top level)</li>
 *   <li>{@code reasoning.effort} (OpenAI Responses API)</li>
 *   <li>{@code output_config.effort} (Anthropic Messages API)</li>
 *   <li>{@code chat_template_kwargs.reasoning_effort} (explicit template kwarg)</li>
 * </ul>
 */
final class GatewayReasoningEffort {

    private GatewayReasoningEffort() {
    }

    /** The lower-cased effort, or {@code null} when the body carries none. */
    static String from(JsonNode root) {
        if (root == null || !root.isObject()) {
            return null;
        }
        String effort = text(root.get("reasoning_effort"));
        if (effort == null) {
            effort = text(root.path("reasoning").get("effort"));
        }
        if (effort == null) {
            effort = text(root.path("output_config").get("effort"));
        }
        if (effort == null) {
            effort = text(root.path("chat_template_kwargs").get("reasoning_effort"));
        }
        return effort;
    }

    private static String text(JsonNode node) {
        if (node == null || !node.isTextual()) {
            return null;
        }
        String value = node.asText().strip();
        return value.isEmpty() ? null : value.toLowerCase(Locale.ROOT);
    }
}
