package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Builds the upstream URL for a cloud forward, porting the essential behaviour
 * of the orchestrator's {@code ContextResolver._cloud_forward_url}.
 *
 * <p>Absolute per-model endpoints win (Azure deployment name + {@code api-version});
 * otherwise {@code base_url} + inbound path, stripping a duplicated {@code /v1}
 * or {@code /v2} prefix. Azure operation suffixes are re-targeted when the
 * client addresses a swappable surface ({@code chat/completions} ↔
 * {@code responses}, audio transcriptions ↔ translations).
 *
 * <p>Does not implement Anthropic Messages path rewriting — those requests
 * stay on the orchestrator path.
 */
public final class CloudForwardUrlBuilder {

    private static final Pattern AZURE_DEPLOYMENT_OP = Pattern.compile(
        "^(?<prefix>https?://[^/]+/openai/deployments/[^/?]+)/(?<operation>[^?]+?)/?(?:\\?(?<query>.*))?$");

    private static final Pattern AZURE_RESPONSES = Pattern.compile(
        "^(?<host>https?://[^/]+)/openai/deployments/(?<deployment>[^/?]+)/responses(?<query>\\?.*)?$");

    private static final Set<String> SWAPPABLE_CHAT = Set.of("chat/completions", "responses");
    private static final Set<String> SWAPPABLE_AUDIO = Set.of("audio/transcriptions", "audio/translations");

    /** Defaults mirror {@code AZURE_OPERATION_API_VERSIONS} in the orchestrator. */
    private static final Map<String, String> AZURE_API_VERSIONS = Map.of(
        "chat/completions", envOr("LOGOS_AZURE_CHAT_API_VERSION", "2025-01-01-preview"),
        "responses", envOr("LOGOS_AZURE_RESPONSES_API_VERSION", "2025-04-01-preview"),
        "embeddings", envOr("LOGOS_AZURE_EMBEDDINGS_API_VERSION", "2024-02-01"),
        "audio/transcriptions", envOr("LOGOS_AZURE_AUDIO_API_VERSION", "2025-04-01-preview"),
        "audio/translations", envOr("LOGOS_AZURE_AUDIO_API_VERSION", "2025-04-01-preview")
    );

    private CloudForwardUrlBuilder() {
    }

    /**
     * @param baseUrl           provider base URL
     * @param requestPath       inbound path (prefer {@code /v1/...}); may be null
     * @param endpointFallback  per-model endpoint (absolute or relative); may be null/blank
     */
    public static String build(String baseUrl, String requestPath, String endpointFallback) {
        String endpoint = endpointFallback == null ? "" : endpointFallback.strip();
        if (endpoint.startsWith("http")) {
            return alignAzureOperation(endpoint, requestPath);
        }
        if (requestPath == null || requestPath.isBlank()) {
            return mergeUrl(baseUrl, endpoint);
        }
        String path = requestPath.strip().replaceFirst("^/+", "");
        String base = baseUrl == null ? "" : baseUrl.strip().replaceAll("/+$", "");
        for (String prefix : new String[] {"v1/", "v2/"}) {
            String versionSeg = "/" + prefix.substring(0, 2);
            if (base.endsWith(versionSeg) && path.startsWith(prefix)) {
                path = path.substring(prefix.length());
                break;
            }
        }
        return base + "/" + path;
    }

    /**
     * Collapse a deployment-scoped Azure Responses URL to Azure's real
     * {@code /openai/responses} route and return the deployment id for body rewrite.
     *
     * @return empty when the URL is not a deployment-scoped Responses endpoint
     */
    public static Optional<AzureResponsesRewrite> azureResponsesRewrite(String forwardUrl) {
        Matcher match = AZURE_RESPONSES.matcher(forwardUrl == null ? "" : forwardUrl);
        if (!match.matches()) {
            return Optional.empty();
        }
        String host = match.group("host");
        String deployment = match.group("deployment");
        String query = match.group("query") == null ? "" : match.group("query");
        return Optional.of(new AzureResponsesRewrite(host + "/openai/responses" + query, deployment));
    }

    public record AzureResponsesRewrite(String realUrl, String deploymentId) {
    }

    static String alignAzureOperation(String endpoint, String requestPath) {
        String requested = requestedOperation(requestPath);
        if (requested == null) {
            return endpoint;
        }
        Matcher match = AZURE_DEPLOYMENT_OP.matcher(endpoint == null ? "" : endpoint);
        if (!match.matches()) {
            return endpoint;
        }
        String current = match.group("operation");
        boolean sameFamily =
            (SWAPPABLE_CHAT.contains(current) && SWAPPABLE_CHAT.contains(requested))
                || (SWAPPABLE_AUDIO.contains(current) && SWAPPABLE_AUDIO.contains(requested));
        if (current.equals(requested) || !sameFamily) {
            return endpoint;
        }
        Map<String, String> params = parseQuery(match.group("query"));
        String apiVersion = AZURE_API_VERSIONS.get(requested);
        if (apiVersion != null) {
            params.put("api-version", apiVersion);
        }
        String query = encodeQuery(params);
        return match.group("prefix") + "/" + requested + query;
    }

    static String requestedOperation(String requestPath) {
        if (requestPath == null || requestPath.isBlank()) {
            return null;
        }
        String path = requestPath.strip().replaceFirst("^/+", "");
        for (String prefix : new String[] {"v1/", "v2/"}) {
            if (path.startsWith(prefix)) {
                path = path.substring(prefix.length());
                break;
            }
        }
        if (SWAPPABLE_CHAT.contains(path) || SWAPPABLE_AUDIO.contains(path)) {
            return path;
        }
        return null;
    }

    static String mergeUrl(String baseUrl, String endpoint) {
        if (endpoint != null && endpoint.startsWith("http")) {
            return endpoint;
        }
        String base = baseUrl == null ? "" : baseUrl.replaceAll("/+$", "");
        String path = endpoint == null ? "" : endpoint.replaceFirst("^/+", "");
        if (path.isEmpty()) {
            return base;
        }
        if (base.isEmpty()) {
            return path;
        }
        return base + "/" + path;
    }

    private static Map<String, String> parseQuery(String query) {
        Map<String, String> params = new LinkedHashMap<>();
        if (query == null || query.isBlank()) {
            return params;
        }
        for (String part : query.split("&")) {
            if (part.isEmpty()) {
                continue;
            }
            int eq = part.indexOf('=');
            if (eq < 0) {
                params.put(part, "");
            } else {
                params.put(part.substring(0, eq), part.substring(eq + 1));
            }
        }
        return params;
    }

    private static String encodeQuery(Map<String, String> params) {
        if (params.isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder("?");
        boolean first = true;
        for (Map.Entry<String, String> e : params.entrySet()) {
            if (!first) {
                sb.append('&');
            }
            first = false;
            sb.append(URLEncoder.encode(e.getKey(), StandardCharsets.UTF_8));
            sb.append('=');
            sb.append(URLEncoder.encode(e.getValue() == null ? "" : e.getValue(), StandardCharsets.UTF_8));
        }
        return sb.toString();
    }

    private static String envOr(String name, String fallback) {
        String v = System.getenv(name);
        return (v == null || v.isBlank()) ? fallback : v.strip();
    }
}
