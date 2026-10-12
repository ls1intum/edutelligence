package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

/**
 * Rows to import. The web application performs the CSV column mapping and the
 * row selection, so the application server receives only the three mapped
 * fields per user. No team is part of the import: users are created without
 * one and added to a team's members afterwards.
 */
public record ImportUsersRequestDTO(List<Row> rows) {

    public record Row(String prename, String name, String email) {}
}
