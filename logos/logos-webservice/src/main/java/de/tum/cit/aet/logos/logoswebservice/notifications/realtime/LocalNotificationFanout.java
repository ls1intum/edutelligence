package de.tum.cit.aet.logos.logoswebservice.notifications.realtime;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/**
 * Single-replica fan-out: pushes straight to this replica's sockets. Selected
 * with {@code logos.notifications.fanout=local} (tests, a lone instance).
 */
@Component
@ConditionalOnProperty(name = "logos.notifications.fanout", havingValue = "local")
public class LocalNotificationFanout implements NotificationFanout {

    private final NotificationSocketHandler sockets;

    public LocalNotificationFanout(NotificationSocketHandler sockets) {
        this.sockets = sockets;
    }

    @Override
    public void publish(NotificationEvent event) {
        sockets.deliverLocally(event);
    }
}
