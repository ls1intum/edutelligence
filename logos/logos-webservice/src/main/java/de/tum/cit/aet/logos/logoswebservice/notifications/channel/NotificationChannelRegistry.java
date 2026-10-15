package de.tum.cit.aet.logos.logoswebservice.notifications.channel;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import de.tum.cit.aet.logos.logoswebservice.notifications.entity.Notification;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationRecipient;

/**
 * Fans a published notification out to every registered channel that claims
 * to handle its type.
 *
 * <p>Spring injects every {@link NotificationChannel} bean, so registering a
 * new delivery mechanism is just adding a component. A channel that throws is
 * logged and skipped, so one failing delivery never breaks the publish or the
 * other channels.
 */
@Component
public class NotificationChannelRegistry {

    private static final Logger log = LoggerFactory.getLogger(NotificationChannelRegistry.class);

    private final List<NotificationChannel> channels;

    public NotificationChannelRegistry(List<NotificationChannel> channels) {
        this.channels = channels;
    }

    public void dispatch(Notification notification, List<NotificationRecipient> recipients) {
        for (NotificationChannel channel : channels) {
            if (!channel.handles(notification.getType())) {
                continue;
            }
            try {
                channel.deliver(notification, recipients);
            } catch (RuntimeException e) {
                log.warn("notification channel {} failed for notification {}",
                    channel.name(), notification.getId(), e);
            }
        }
    }
}
