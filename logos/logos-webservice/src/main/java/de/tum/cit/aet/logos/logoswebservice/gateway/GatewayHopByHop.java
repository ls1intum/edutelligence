package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.Enumeration;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Hop-by-hop header filtering for gateway proxies (RFC 9110 §7.6.1).
 */
final class GatewayHopByHop {

    private static final Set<String> BASE = Set.of(
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length",
        // h2c preface — must not be copied when re-buffering the body.
        "http2-settings",
        // JDK HttpClient rejects these restricted request headers.
        "expect"
    );

    private GatewayHopByHop() {
    }

    /** Whether a request header must not be forwarded upstream (base set only). */
    static boolean isRequestHopByHop(String name) {
        return name != null && BASE.contains(name.toLowerCase(Locale.ROOT));
    }

    /**
     * Build the set of request header names that must not be forwarded:
     * the base hop-by-hop set plus every field nominated by {@code Connection}.
     */
    static Set<String> requestExcludeNames(Enumeration<String> connectionValues) {
        Set<String> exclude = new HashSet<>(BASE);
        if (connectionValues == null) {
            return exclude;
        }
        while (connectionValues.hasMoreElements()) {
            addConnectionTokens(exclude, connectionValues.nextElement());
        }
        return exclude;
    }

    /**
     * Build the set of response header names that must not be forwarded to the
     * client: the base hop-by-hop set plus every field nominated by
     * {@code Connection}.
     */
    static Set<String> responseExcludeNames(Map<String, List<String>> upstreamHeaders) {
        Set<String> exclude = new HashSet<>(BASE);
        if (upstreamHeaders == null) {
            return exclude;
        }
        for (Map.Entry<String, List<String>> e : upstreamHeaders.entrySet()) {
            if (e.getKey() == null || !"connection".equalsIgnoreCase(e.getKey()) || e.getValue() == null) {
                continue;
            }
            for (String value : e.getValue()) {
                addConnectionTokens(exclude, value);
            }
        }
        return exclude;
    }

    private static void addConnectionTokens(Set<String> exclude, String value) {
        if (value == null) {
            return;
        }
        for (String token : value.split(",")) {
            String t = token.strip().toLowerCase(Locale.ROOT);
            if (!t.isEmpty()) {
                exclude.add(t);
            }
        }
    }
}
