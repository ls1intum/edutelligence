package de.tum.cit.aet.logos.logoswebservice.auth;

public record AuthContext(
    String keyValue,
    Integer apiKeyId,
    String keyName,
    String keyType,
    Integer teamId,
    Integer userId,
    String role
) {}
