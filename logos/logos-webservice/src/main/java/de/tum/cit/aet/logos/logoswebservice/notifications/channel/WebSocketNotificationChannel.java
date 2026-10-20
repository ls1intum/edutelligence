package de.tum.cit.aet.logos.logoswebservice.notifications.channel;

import java.util.List;

import org.springframework.stereotype.Component;

import de.tum.cit.aet.logos.logoswebservice.notifications.entity.Notification;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationRecipient;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.NotificationType;
import de.tum.cit.aet.logos.logoswebservice.notifications.realtime.NotificationEvent;
import de.tum.cit.aet.logos.logoswebservice.notifications.realtime.NotificationFanout;
import de.tum.cit.aet.logos.logoswebservice.notifications.service.NotificationMapper;

/**
 * In-app live delivery: pushes every new notification to the open
 * {@code /ws/notifications} sockets of the people it is addressed to, on
 * whichever replica they are connected.
 */
@Component
public class WebSocketNotificationChannel implements NotificationChannel {

    private final NotificationFanout fanout;
    private final NotificationMapper mapper;

    public WebSocketNotificationChannel(NotificationFanout fanout, NotificationMapper mapper) {
        this.fanout = fanout;
        this.mapper = mapper;
    }

    @Override
    public String name() {
        return "websocket";
    }

    @Override
    public boolean handles(NotificationType type) {
        return true;
    }

    @Override
    public void deliver(Notification notification, List<NotificationRecipient> recipients) {
        fanout.publish(new NotificationEvent(
            notification.getId(), mapper.toWire(mapper.toDto(notification, false))));
    }
}
