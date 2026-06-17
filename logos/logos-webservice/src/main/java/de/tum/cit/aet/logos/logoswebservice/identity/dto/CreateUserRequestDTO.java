package de.tum.cit.aet.logos.logoswebservice.identity.dto;
import java.util.List;

public record CreateUserRequestDTO(
    String prename,
    String name,
    String email,
    String role,
    List<Integer> team_ids
) {}
