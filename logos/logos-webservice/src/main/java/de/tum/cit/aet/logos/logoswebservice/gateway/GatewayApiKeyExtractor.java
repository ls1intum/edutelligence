package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.Locale;

import jakarta.servlet.http.HttpServletRequest;

/**
 * Extracts a Logos API key from the inbound request headers.
 *
 * <p>Same precedence as {@code ModelController.extractApiKey}: {@code logos_key},
 * {@code logos-key}, then {@code Authorization: Bearer}.
 */
public final class GatewayApiKeyExtractor {

    private GatewayApiKeyExtractor() {
    }

    /**
     * @return the stripped key value, or {@code null} when absent / blank
     */
    public static String extract(HttpServletRequest request) {
        String key = request.getHeader("logos_key");
        if (key == null || key.isBlank()) {
            key = request.getHeader("logos-key");
        }
        if (key == null || key.isBlank()) {
            String authorization = request.getHeader("Authorization");
            if (authorization != null && authorization.toLowerCase(Locale.ROOT).startsWith("bearer ")) {
                key = authorization.substring("bearer ".length());
            }
        }
        if (key == null) {
            return null;
        }
        key = key.strip();
        return key.isEmpty() ? null : key;
    }
}
