package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

public record MeResponseDTO(
    Integer user_id,
    String username,
    String email,
    String role,
    List<TeamResponseDTO> teams
) {}
