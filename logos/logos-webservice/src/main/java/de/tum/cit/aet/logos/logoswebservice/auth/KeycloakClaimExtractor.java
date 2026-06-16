package de.tum.cit.aet.logos.logoswebservice.auth;

import java.util.Collection;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.stereotype.Component;

@Component
public class KeycloakClaimExtractor {

    private final KeycloakProperties props;

    public KeycloakClaimExtractor(KeycloakProperties props) {
        this.props = props;
    }

    public KeycloakClaims extract(Jwt jwt) {
        Set<String> roleNames = new HashSet<>();

        Map<String, Object> realmAccess = jwt.getClaimAsMap("realm_access");
        addRoles(roleNames, realmAccess);

        Map<String, Object> resourceAccess = jwt.getClaimAsMap("resource_access");
        if (resourceAccess != null && resourceAccess.get(props.clientId()) instanceof Map<?, ?> clientAccess) {
            addRoles(roleNames, clientAccess);
        }

        if (jwt.getClaim("groups") instanceof Collection<?> groups) {
            for (Object g : groups) {
                if (g instanceof String s) {
                    roleNames.add(normalizeGroupName(s));
                }
            }
        }

        return new KeycloakClaims(
            jwt.getSubject(),
            null,
            orEmpty(jwt.getClaimAsString("given_name")),
            orEmpty(jwt.getClaimAsString("family_name")),
            jwt.getClaimAsString("email"),
            roleNames,
            jwt.getIssuedAt());
    }

    public static String normalizeGroupName(String group) {
        if (group == null) return null;
        return group.startsWith("/") ? group.substring(1) : group;
    }

    private static void addRoles(Set<String> target, Map<?, ?> access) {
        if (access != null && access.get("roles") instanceof Collection<?> roles) {
            for (Object r : roles) {
                if (r instanceof String s) target.add(s);
            }
        }
    }

    private static String orEmpty(String s) {
        return s != null ? s : "";
    }
}
