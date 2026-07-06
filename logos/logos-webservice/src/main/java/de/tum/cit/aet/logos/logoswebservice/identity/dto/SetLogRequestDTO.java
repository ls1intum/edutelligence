package de.tum.cit.aet.logos.logoswebservice.identity.dto;

public record SetLogRequestDTO(
    Integer apiKeyId,
    Integer processId,
    String setLog
) {}
