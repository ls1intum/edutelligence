package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Query-string helpers for cloud forward URLs.
 */
final class GatewayQueryMerge {

    private GatewayQueryMerge() {
    }

    /**
     * Merge an inbound query string into {@code url}. Provider parameters
     * (already on the URL, e.g. Azure {@code api-version}) are kept; inbound
     * keys override on conflict so clients can still pass extras.
     */
    static String merge(String url, String inboundQuery) {
        if (url == null) {
            return null;
        }
        if (inboundQuery == null || inboundQuery.isBlank()) {
            return url;
        }
        String inbound = inboundQuery.startsWith("?") ? inboundQuery.substring(1) : inboundQuery;
        if (inbound.isBlank()) {
            return url;
        }
        int q = url.indexOf('?');
        if (q < 0) {
            return url + "?" + inbound;
        }
        Map<String, String> params = new LinkedHashMap<>();
        parseInto(url.substring(q + 1), params);
        parseInto(inbound, params);
        StringBuilder sb = new StringBuilder(url.substring(0, q + 1));
        boolean first = true;
        for (Map.Entry<String, String> e : params.entrySet()) {
            if (!first) {
                sb.append('&');
            }
            first = false;
            sb.append(e.getKey());
            if (e.getValue() != null) {
                sb.append('=').append(e.getValue());
            }
        }
        return sb.toString();
    }

    private static void parseInto(String query, Map<String, String> out) {
        if (query == null || query.isBlank()) {
            return;
        }
        for (String part : query.split("&")) {
            if (part.isEmpty()) {
                continue;
            }
            int eq = part.indexOf('=');
            if (eq < 0) {
                out.put(part, null);
            } else {
                out.put(part.substring(0, eq), part.substring(eq + 1));
            }
        }
    }
}
