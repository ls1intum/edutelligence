package de.tum.cit.aet.logos.logoswebservice.identity.dto;
import java.util.List;

public record CreateTeamRequest(String name, List<Integer> owner_ids) {}