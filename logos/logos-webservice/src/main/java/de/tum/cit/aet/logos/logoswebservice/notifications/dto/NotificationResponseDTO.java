package de.tum.cit.aet.logos.logoswebservice.notifications.dto;

import java.time.Instant;

/**
 * One inbox entry as returned to the caller.
 *
 * @param id          notification id
 * @param type        the {@code NotificationType} value (e.g. {@code budget_hit})
 * @param title       short human summary
 * @param body        optional longer text
 * @param payload     event-specific structured data (parsed from JSONB), or null
 * @param source      {@code webservice} or {@code orchestrator}
 * @param actorUserId user who triggered the event, or null
 * @param createdAt   when it was emitted
 * @param read        whether the caller has already read it
 */
public record NotificationResponseDTO(
    Long id,
    String type,
    String title,
    String body,
    Object payload,
    String source,
    Integer actorUserId,
    Instant createdAt,
    boolean read
) {}
