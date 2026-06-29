package de.tum.cit.aet.logos.logoswebservice.identity.dto;
import java.util.List;
import java.util.Map;

public record TeamDetailResponseDTO(Map<String, Object> team, List<Map<String, Object>> members) {}
