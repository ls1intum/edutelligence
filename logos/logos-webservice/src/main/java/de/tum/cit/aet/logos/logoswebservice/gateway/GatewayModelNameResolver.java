package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * Resolves a client-supplied model id to a canonical DB model name.
 *
 * <p>Ports {@code _resolve_requested_model_name} from the orchestrator's
 * {@code logosnode_snapshot.py}: case-insensitive canonical name, stored
 * alias, planner-safe alias ({@code /}:space → {@code _}), and replica lane
 * ids ({@code planner-<alias>-N}, {@code N >= 2}). Ambiguous matches return
 * {@code null}.
 */
final class GatewayModelNameResolver {

    private GatewayModelNameResolver() {
    }

    /**
     * @param availableModels models the key may use; each entry is
     *                        {@code (canonicalName, aliases)}
     * @return canonical name, or {@code null} when unresolved / ambiguous
     */
    static String resolve(String requestedName, List<ModelNames> availableModels) {
        String requested = requestedName == null ? "" : requestedName.strip();
        if (requested.isEmpty() || availableModels == null || availableModels.isEmpty()) {
            return null;
        }
        String requestedLc = requested.toLowerCase(Locale.ROOT);

        Set<String> knownNames = new HashSet<>();
        for (ModelNames entry : availableModels) {
            String canonical = entry.canonical();
            if (canonical == null || canonical.isBlank()) {
                continue;
            }
            knownNames.add(canonical.toLowerCase(Locale.ROOT));
            knownNames.add(plannerAlias(canonical).toLowerCase(Locale.ROOT));
            for (String alias : entry.aliases()) {
                if (alias != null && !alias.isBlank()) {
                    knownNames.add(alias.strip().toLowerCase(Locale.ROOT));
                    knownNames.add(plannerAlias(alias).toLowerCase(Locale.ROOT));
                }
            }
        }

        Set<String> canonicalMatches = new LinkedHashSet<>();
        Set<String> storedAliasMatches = new LinkedHashSet<>();
        Set<String> plannerAliasMatches = new LinkedHashSet<>();
        Set<String> replicaMatches = new LinkedHashSet<>();

        for (ModelNames entry : availableModels) {
            String canonical = entry.canonical();
            if (canonical == null || canonical.isBlank()) {
                continue;
            }
            if (canonical.toLowerCase(Locale.ROOT).equals(requestedLc)) {
                canonicalMatches.add(canonical);
                continue;
            }

            String sanitized = plannerAlias(canonical);
            String sanitizedLc = sanitized.toLowerCase(Locale.ROOT);
            if (requestedLc.equals(sanitizedLc) || requestedLc.equals("planner-" + sanitizedLc)) {
                plannerAliasMatches.add(canonical);
            }
            for (String alias : entry.aliases()) {
                if (alias != null && alias.strip().toLowerCase(Locale.ROOT).equals(requestedLc)) {
                    storedAliasMatches.add(canonical);
                }
            }

            String replicaPrefix = "planner-" + sanitizedLc + "-";
            if (requestedLc.startsWith(replicaPrefix)) {
                String suffix = requestedLc.substring(replicaPrefix.length());
                if (isAsciiDigits(suffix)) {
                    try {
                        int index = Integer.parseInt(suffix);
                        if (index >= 2 && !knownNames.contains(sanitizedLc + "-" + suffix)) {
                            replicaMatches.add(canonical);
                        }
                    } catch (NumberFormatException ignored) {
                        // refuse oversized / unparsable replica suffixes
                    }
                }
            }
        }

        if (canonicalMatches.size() == 1) {
            return canonicalMatches.iterator().next();
        }
        if (!canonicalMatches.isEmpty()) {
            return null;
        }
        if (storedAliasMatches.size() == 1) {
            return storedAliasMatches.iterator().next();
        }
        if (!storedAliasMatches.isEmpty()) {
            return null;
        }
        if (plannerAliasMatches.size() == 1) {
            return plannerAliasMatches.iterator().next();
        }
        if (!plannerAliasMatches.isEmpty()) {
            return null;
        }
        if (replicaMatches.size() == 1) {
            return replicaMatches.iterator().next();
        }
        return null;
    }

    static String plannerAlias(String modelName) {
        String raw = modelName == null ? "" : modelName.strip();
        return raw.replace('/', '_').replace(':', '_').replace(' ', '_');
    }

    private static boolean isAsciiDigits(String s) {
        if (s == null || s.isEmpty()) {
            return false;
        }
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c < '0' || c > '9') {
                return false;
            }
        }
        return true;
    }

    /** Canonical model name plus stored aliases. */
    record ModelNames(String canonical, List<String> aliases) {
        ModelNames {
            aliases = aliases == null ? List.of() : List.copyOf(aliases);
        }

        static ModelNames of(String canonical, String commaJoinedAliases) {
            List<String> aliases = new ArrayList<>();
            if (commaJoinedAliases != null && !commaJoinedAliases.isBlank()) {
                for (String part : commaJoinedAliases.split(",")) {
                    String a = part.strip();
                    if (!a.isEmpty()) {
                        aliases.add(a);
                    }
                }
            }
            return new ModelNames(canonical, aliases);
        }
    }
}
