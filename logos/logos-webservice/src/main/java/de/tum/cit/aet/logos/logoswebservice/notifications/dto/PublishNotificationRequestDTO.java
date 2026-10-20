package de.tum.cit.aet.logos.logoswebservice.notifications.dto;

import java.util.List;
import java.util.Map;

/**
 * Payload for publishing a notification (the internal emission endpoint, and
 * any future in-process producer).
 *
 * @param type        one of the {@code NotificationType} values (e.g. {@code budget_hit})
 * @param title       short human summary shown in the inbox (required)
 * @param body        optional longer text
 * @param payload     optional event-specific structured data, stored as JSONB
 * @param source      {@code webservice} or {@code orchestrator}; the internal
 *                    endpoint forces {@code orchestrator}
 * @param actorUserId optional user who triggered the event
 * @param targets     at least one fan-out target (user / team / role)
 */
public record PublishNotificationRequestDTO(
    String type,
    String title,
    String body,
    Map<String, Object> payload,
    String source,
    Integer actorUserId,
    List<NotificationTargetDTO> targets
) {}
