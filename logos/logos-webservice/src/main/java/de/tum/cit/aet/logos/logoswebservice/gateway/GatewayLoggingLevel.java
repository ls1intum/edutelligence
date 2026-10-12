package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.Locale;
import java.util.Map;

import jakarta.servlet.http.HttpServletRequest;

/**
 * Per-request logging level for the direct-cloud gateway path.
 *
 * <p>Mirrors the orchestrator's {@code resolve_log_level}: the key's configured
 * level is the default; a {@code logos-logging} / {@code logos_logging} header
 * overrides it when present. Recognised values are the level names
 * ({@code FULL}, {@code BILLING}) and the plain words {@code yes}/{@code no}
 * (case-insensitive). A present but unrecognised value fails closed to
 * {@code BILLING}.
 */
final class GatewayLoggingLevel {

    static final String LEVEL_FULL = "FULL";
    static final String LEVEL_BILLING = "BILLING";

    private static final String HEADER = "logos-logging";
    private static final String HEADER_ALT = "logos_logging";

    private static final Map<String, String> WORDS = Map.of(
        "YES", LEVEL_FULL,
        "NO", LEVEL_BILLING,
        LEVEL_FULL, LEVEL_FULL,
        LEVEL_BILLING, LEVEL_BILLING
    );

    private GatewayLoggingLevel() {
    }

    /**
     * Resolve the effective logging level for one request.
     *
     * @param request      the incoming request (may be {@code null}, treated as no header)
     * @param keyLogLevel  the key's configured level (may be {@code null})
     * @return {@code FULL} or {@code BILLING}
     */
    static String resolve(HttpServletRequest request, String keyLogLevel) {
        String raw = headerValue(request);
        if (raw == null || raw.isBlank()) {
            return LEVEL_FULL.equalsIgnoreCase(keyLogLevel) ? LEVEL_FULL : LEVEL_BILLING;
        }
        return normalize(raw);
    }

    /** Whether a resolved level stores request and response payloads. */
    static boolean storesPayloads(String logLevel) {
        return LEVEL_FULL.equalsIgnoreCase(logLevel);
    }

    private static String normalize(String raw) {
        String value = raw.strip().toUpperCase(Locale.ROOT);
        return WORDS.getOrDefault(value, LEVEL_BILLING);
    }

    private static String headerValue(HttpServletRequest request) {
        if (request == null) {
            return null;
        }
        String primary = request.getHeader(HEADER);
        if (primary != null) {
            return primary;
        }
        return request.getHeader(HEADER_ALT);
    }
}
