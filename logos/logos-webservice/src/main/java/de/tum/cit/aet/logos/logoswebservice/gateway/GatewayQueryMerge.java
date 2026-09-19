package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Query-string helpers for cloud forward URLs.
 *
 * <p>Preserves repeated keys (ordered multimap). Provider parameters already
 * on the URL are kept unless an inbound key overrides that key (all inbound
 * values for an overriding key replace all provider values for it).
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
        List<Pair> base = parse(url.substring(q + 1));
        List<Pair> extra = parse(inbound);
        Map<String, List<String>> override = new LinkedHashMap<>();
        for (Pair p : extra) {
            override.computeIfAbsent(p.key(), k -> new ArrayList<>()).add(p.value());
        }
        List<Pair> merged = new ArrayList<>();
        for (Pair p : base) {
            if (!override.containsKey(p.key())) {
                merged.add(p);
            }
        }
        for (Map.Entry<String, List<String>> e : override.entrySet()) {
            for (String v : e.getValue()) {
                merged.add(new Pair(e.getKey(), v));
            }
        }
        StringBuilder sb = new StringBuilder(url.substring(0, q + 1));
        boolean first = true;
        for (Pair p : merged) {
            if (!first) {
                sb.append('&');
            }
            first = false;
            sb.append(p.key());
            if (p.value() != null) {
                sb.append('=').append(p.value());
            }
        }
        return sb.toString();
    }

    private static List<Pair> parse(String query) {
        List<Pair> out = new ArrayList<>();
        if (query == null || query.isBlank()) {
            return out;
        }
        for (String part : query.split("&")) {
            if (part.isEmpty()) {
                continue;
            }
            int eq = part.indexOf('=');
            if (eq < 0) {
                out.add(new Pair(part, null));
            } else {
                out.add(new Pair(part.substring(0, eq), part.substring(eq + 1)));
            }
        }
        return out;
    }

    private record Pair(String key, String value) {
    }
}
