package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

/**
 * Cloud upstream auth and protocol headers, ported from the orchestrator's
 * {@code logos.dbutils.types.cloud_auth_header} / {@code cloud_protocol_headers}.
 */
public final class CloudAuthHeaders {

    /** Matches {@code ANTHROPIC_VERSION} default in the orchestrator. */
    public static final String ANTHROPIC_VERSION = envOr("LOGOS_ANTHROPIC_VERSION", "2023-06-01");

    private CloudAuthHeaders() {
    }

    /**
     * HTTP auth header a cloud provider's stored credentials produce.
     *
     * @return empty when there is no key to send
     */
    public static Optional<Header> authHeader(
            String authName,
            String authFormat,
            String apiKey,
            String cloudProviderType) {
        if (apiKey == null || apiKey.isBlank()) {
            return Optional.empty();
        }
        String name = authName == null ? "" : authName.strip();
        String fmt = authFormat == null ? "" : authFormat;
        if (name.isEmpty()) {
            String type = cloudProviderType == null ? "" : cloudProviderType.toLowerCase(Locale.ROOT);
            if ("anthropic".equals(type)) {
                name = "x-api-key";
                if (fmt.isEmpty()) {
                    fmt = "{}";
                }
            } else {
                name = "Authorization";
                if (fmt.isEmpty()) {
                    fmt = "Bearer {}";
                }
            }
        } else if (fmt.isEmpty()) {
            fmt = "{}";
        }
        return Optional.of(new Header(name, fmt.replace("{}", apiKey)));
    }

    /**
     * Headers a provider's protocol requires on every request (Anthropic version).
     */
    public static Map<String, String> protocolHeaders(String cloudProviderType) {
        if (cloudProviderType != null
            && "anthropic".equals(cloudProviderType.toLowerCase(Locale.ROOT))) {
            Map<String, String> headers = new LinkedHashMap<>();
            headers.put("anthropic-version", ANTHROPIC_VERSION);
            return headers;
        }
        return Collections.emptyMap();
    }

    public record Header(String name, String value) {
    }

    private static String envOr(String name, String fallback) {
        String v = System.getenv(name);
        return (v == null || v.isBlank()) ? fallback : v.strip();
    }
}
