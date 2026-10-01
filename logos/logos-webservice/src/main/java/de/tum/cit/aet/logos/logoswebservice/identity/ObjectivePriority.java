package de.tum.cit.aet.logos.logoswebservice.identity;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * Ordered optimization objectives for an LLM call site (most important first).
 * Complements SLA: SLA answers urgency; this answers what to optimize for.
 */
public final class ObjectivePriority {

    public static final List<String> KNOWN = List.of("latency", "quality", "price");
    private static final Set<String> KNOWN_SET = Set.copyOf(KNOWN);
    public static final List<String> DEFAULT = List.copyOf(KNOWN);

    private ObjectivePriority() {}

    /** Heuristic default ranking derived from the SLA tier. */
    public static List<String> forSla(String sla) {
        if (sla == null) {
            return DEFAULT;
        }
        return switch (sla.trim().toLowerCase(Locale.ROOT)) {
            case "ux-critical" -> List.of("latency", "quality", "price");
            case "ux-background" -> List.of("price", "quality", "latency");
            default -> List.of("quality", "latency", "price");
        };
    }

    /**
     * Normalize an incoming list: lowercase known keys, drop unknowns/dupes,
     * append any missing known keys so the result is always a full ranking.
     */
    public static List<String> normalize(List<?> raw) {
        if (raw == null || raw.isEmpty()) {
            return DEFAULT;
        }
        LinkedHashSet<String> ordered = new LinkedHashSet<>();
        for (Object item : raw) {
            if (item == null) {
                continue;
            }
            String key = String.valueOf(item).trim().toLowerCase(Locale.ROOT);
            if (KNOWN_SET.contains(key)) {
                ordered.add(key);
            }
        }
        for (String key : KNOWN) {
            ordered.add(key);
        }
        return List.copyOf(ordered);
    }

    public static List<String> asStringList(Object stored) {
        if (stored instanceof List<?> list) {
            return normalize(list);
        }
        return DEFAULT;
    }

    /** Shallow mutable copy for JPA JSONB maps that expect List&lt;Object&gt;. */
    public static List<Object> asJsonList(List<String> priority) {
        return new ArrayList<>(normalize(priority));
    }
}
