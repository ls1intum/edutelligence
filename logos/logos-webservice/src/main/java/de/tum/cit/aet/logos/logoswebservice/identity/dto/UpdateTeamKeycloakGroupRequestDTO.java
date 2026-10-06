package de.tum.cit.aet.logos.logoswebservice.identity.dto;

/**
 * @param keycloak_group the Keycloak group to link; null or blank unlinks the team.
 */
public record UpdateTeamKeycloakGroupRequestDTO(String keycloak_group) {}
