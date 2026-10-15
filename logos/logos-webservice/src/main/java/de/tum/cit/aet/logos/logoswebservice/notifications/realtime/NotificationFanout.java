package de.tum.cit.aet.logos.logoswebservice.notifications.realtime;

/**
 * Gets a published notification to the sockets of every application server
 * replica. A notification is published on one replica, but its recipients'
 * sockets can be open on any of them.
 */
public interface NotificationFanout {

    void publish(NotificationEvent event);
}
