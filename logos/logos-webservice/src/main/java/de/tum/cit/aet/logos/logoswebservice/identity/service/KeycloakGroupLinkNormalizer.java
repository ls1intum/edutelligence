package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.util.LinkedHashSet;
import java.util.Set;

import org.springframework.stereotype.Component;

import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakClaimExtractor;
import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakProperties;

/**
 * Turns the Keycloak group a Logos admin types into the exact string a login
 * claim carries, and rejects the values that could never resolve to a team.
 *
 * <p>A claim name reaching {@code KeycloakUserSyncService} is either a realm /
 * client role name or a group path with its leading {@code /} removed, so a
 * link stored with the slash still on it would simply never match. The
 * platform admin roles are the second dead end: the membership sync removes
 * them from the claim set before resolving teams, so a team linked to one of
 * them would stay empty forever.
 */
@Component
public class KeycloakGroupLinkNormalizer {

    private final KeycloakProperties props;

    public KeycloakGroupLinkNormalizer(KeycloakProperties props) {
        this.props = props;
    }

    /**
     * @param raw the value as it arrived from the request; null or blank means "no link"
     * @return the normalized group name, or null when the team should not be linked
     * @throws IllegalArgumentException if the value cannot name a Keycloak group
     */
    public String normalize(String raw) {
        if (raw == null) return null;
        String trimmed = raw.trim();
        if (trimmed.isEmpty()) return null;

        String normalized = KeycloakClaimExtractor.normalizeGroupName(trimmed).trim();
        if (normalized.isEmpty()) {
            throw new IllegalArgumentException("'" + raw + "' is not a Keycloak group name.");
        }
        // The platform admin roles are matched case-sensitively when the sync
        // strips user-level roles from the claim set, so reserve exactly those
        // spellings — a differently cased group is a different group.
        if (reservedNames().contains(normalized)) {
            throw new IllegalArgumentException("'" + normalized
                + "' grants a platform role and cannot be linked to a team.");
        }
        return normalized;
    }

    /** The configured admin role names, which never map to a team. */
    public Set<String> reservedNames() {
        Set<String> reserved = new LinkedHashSet<>(props.roles().logosAdmin());
        reserved.addAll(props.roles().appAdmin());
        return reserved;
    }
}
