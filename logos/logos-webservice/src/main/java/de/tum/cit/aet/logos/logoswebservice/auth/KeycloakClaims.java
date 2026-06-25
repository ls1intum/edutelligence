package de.tum.cit.aet.logos.logoswebservice.auth;

import java.time.Instant;
import java.util.Set;

public record KeycloakClaims(
    String keycloakId,
    String username,
    String prename,
    String name,
    String email,
    Set<String> roleNames,
    Instant issuedAt
) {}
