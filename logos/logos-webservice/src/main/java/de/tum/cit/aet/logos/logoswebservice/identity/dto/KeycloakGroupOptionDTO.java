package de.tum.cit.aet.logos.logoswebservice.identity.dto;

/**
 * One Keycloak claim name a team can be linked to.
 *
 * @param name            the name as a login claim carries it (group paths without the leading '/')
 * @param source          "group" or "role" — both reach the membership sync as claim names
 * @param linked_team_id  the team already holding this link, if any
 * @param linked_team_name name of that team, for the "already in use" hint
 */
public record KeycloakGroupOptionDTO(
    String name,
    String source,
    Integer linked_team_id,
    String linked_team_name
) {}
