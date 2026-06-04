package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

public record MeResponse(
    Integer user_id,
    String username,
    String email,
    String role,
    List<TeamResponse> teams
) {}