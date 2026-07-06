package de.tum.cit.aet.logos.logoswebservice.auth;

public record AuthContext(
    Integer userId,
    String role
) {}
