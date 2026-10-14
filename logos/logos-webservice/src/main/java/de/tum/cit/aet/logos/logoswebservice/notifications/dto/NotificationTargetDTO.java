package de.tum.cit.aet.logos.logoswebservice.notifications.dto;

/**
 * One fan-out target of a notification to be published.
 *
 * @param kind one of {@code user}, {@code team}, {@code role}
 * @param id   user id ({@code user}) or team id ({@code team}); ignored for {@code role}
 * @param role role value ({@code role}); ignored for {@code user}/{@code team}
 */
public record NotificationTargetDTO(
    String kind,
    Integer id,
    String role
) {}
