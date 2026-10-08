package de.tum.cit.aet.logos.logoswebservice.identity.dto;

import java.util.List;

/**
 * @param available false when the deployment runs without Keycloak directory
 *                  access (logos.auth.sync.enabled=false) or the realm could
 *                  not be read — the group then has to be typed by hand
 * @param groups    the selectable claim names, empty when unavailable
 */
public record KeycloakGroupDirectoryResponseDTO(boolean available, List<KeycloakGroupOptionDTO> groups) {}
