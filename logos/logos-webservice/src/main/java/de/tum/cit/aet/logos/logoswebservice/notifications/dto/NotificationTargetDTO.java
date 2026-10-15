package de.tum.cit.aet.logos.logoswebservice.notifications.dto;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;

/**
 * One fan-out target of a notification to be published.
 *
 * <p>Producers inside the application server build targets with the
 * factories ({@code NotificationTargetDTO.team(teamId)}); the record shape is
 * also the JSON the orchestrator posts.
 *
 * @param kind one of {@code user}, {@code team}, {@code role}
 * @param id   user id ({@code user}) or team id ({@code team}); ignored for {@code role}
 * @param role role value ({@code role}); ignored for {@code user}/{@code team}
 */
public record NotificationTargetDTO(
    String kind,
    Integer id,
    String role
) {

    public static NotificationTargetDTO user(Integer userId) {
        return new NotificationTargetDTO("user", userId, null);
    }

    public static NotificationTargetDTO team(Integer teamId) {
        return new NotificationTargetDTO("team", teamId, null);
    }

    public static NotificationTargetDTO role(Role role) {
        return new NotificationTargetDTO("role", null, role.getValue());
    }
}
