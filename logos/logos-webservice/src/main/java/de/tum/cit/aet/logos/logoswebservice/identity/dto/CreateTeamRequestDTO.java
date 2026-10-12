package de.tum.cit.aet.logos.logoswebservice.identity.dto;
import java.util.List;

/**
 * @param keycloak_group Keycloak group whose members join the team on login;
 *                       null or blank leaves the team unlinked. Logos admins only.
 */
public record CreateTeamRequestDTO(String name, List<Integer> owner_ids, String keycloak_group) {}
