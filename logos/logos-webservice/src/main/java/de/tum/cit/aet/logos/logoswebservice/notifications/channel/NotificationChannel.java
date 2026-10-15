package de.tum.cit.aet.logos.logoswebservice.notifications.channel;

import java.util.List;

import de.tum.cit.aet.logos.logoswebservice.notifications.entity.Notification;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationRecipient;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationType;

/**
 * A delivery mechanism for notifications.
 *
 * <p>This is the modular seam: the persistence and read paths of the system
 * are independent of how a notification is actually surfaced. A new
 * delivery mechanism (an email sender, a websocket push, an outgoing
 * webhook) is a new implementation of this interface annotated with
 * {@code @Component}; the registry picks it up automatically and no caller
 * of the publish API changes.
 *
 * <p>The in-app inbox is not a channel in this sense — the stored row <i>is</i>
 * the in-app notification, surfaced by the read API. Channels are the
 * additional deliveries on top of that.
 */
public interface NotificationChannel {

    /** Stable identifier for logs and diagnostics. */
    String name();

    /** @return whether this channel should receive notifications of {@code type}. */
    boolean handles(NotificationType type);

    /**
     * Deliver a persisted notification to its recipients. Called after the
     * notification is committed, so a delivery that reads the database back
     * sees the row. Implementations must not throw to take the rest of the
     * channels down; the registry already isolates failures.
     */
    void deliver(Notification notification, List<NotificationRecipient> recipients);
}
