package de.tum.cit.aet.logos.logoswebservice.identity.dto;

public record LogosKeyResponseDTO(
    Integer id,
    String name,
    String keyValue,
    Integer teamId,
    String teamName
) {}
