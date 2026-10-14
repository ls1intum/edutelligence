package de.tum.cit.aet.logos.logoswebservice.notifications.channel;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import de.tum.cit.aet.logos.logoswebservice.notifications.entity.Notification;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationRecipient;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationType;

/**
 * Sample channel: it delivers by logging.
 *
 * <p>This exists to make the modular seam concrete and observable — it proves
 * that a {@link NotificationChannel} is discovered, filtered by type, and
 * invoked on publish, with nothing else to configure. It is not a real
 * delivery mechanism; a production channel (email, websocket, webhook) is
 * added the same way and this one can stay, go, or be replaced without
 * touching the publish path.
 */
@Component
public class LoggingNotificationChannel implements NotificationChannel {

    private static final Logger log = LoggerFactory.getLogger(LoggingNotificationChannel.class);

    @Override
    public String name() {
        return "logging";
    }

    @Override
    public boolean handles(NotificationType type) {
        return true;
    }

    @Override
    public void deliver(Notification notification, List<NotificationRecipient> recipients) {
        log.info("notification {} type={} source={} delivered to {} target(s)",
            notification.getId(), notification.getType().name(), notification.getSource(),
            recipients == null ? 0 : recipients.size());
    }
}
