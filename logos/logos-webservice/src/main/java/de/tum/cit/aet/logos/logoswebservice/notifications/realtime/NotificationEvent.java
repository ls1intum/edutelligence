package de.tum.cit.aet.logos.logoswebservice.notifications.realtime;

import java.util.Map;

/**
 * What a replica hands to every replica (over Redis) so each can push to its
 * own open sockets: the notification as the inbox renders it. Each replica
 * decides from the database which of its sockets may receive it.
 *
 * @param notificationId the persisted notification, for the recipient check
 * @param notification   the inbox item, keys already in the wire format
 */
public record NotificationEvent(Long notificationId, Map<String, Object> notification) {
}
