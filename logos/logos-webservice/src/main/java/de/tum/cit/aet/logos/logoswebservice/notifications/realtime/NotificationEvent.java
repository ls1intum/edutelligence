package de.tum.cit.aet.logos.logoswebservice.notifications.realtime;

import java.util.List;
import java.util.Map;

import de.tum.cit.aet.logos.logoswebservice.notifications.dto.NotificationTargetDTO;

/**
 * What a replica hands to every replica (over Redis) so each can push to its
 * own open sockets: the notification as the inbox renders it, plus the targets
 * it is addressed to, which decide which sockets get it.
 *
 * @param notification the inbox item, keys already in the wire format
 * @param targets      the fan-out targets of the notification
 */
public record NotificationEvent(Map<String, Object> notification, List<NotificationTargetDTO> targets) {
}
