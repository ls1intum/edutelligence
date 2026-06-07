package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

public record UserResponse(
    Integer id,
    String username,
    String prename,
    String name,
    String role,
    String email,
    List<TeamResponse> teams
) {}
