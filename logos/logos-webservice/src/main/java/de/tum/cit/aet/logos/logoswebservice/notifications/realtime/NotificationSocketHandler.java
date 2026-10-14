package de.tum.cit.aet.logos.logoswebservice.notifications.realtime;

import java.io.IOException;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.ConcurrentWebSocketSessionDecorator;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.notifications.repository.NotificationRepository;

/**
 * {@code /ws/notifications}: the push half of the inbox.
 *
 * <p>The socket only announces new notifications to the users they are
 * addressed to; it carries no commands. Read state, history and the unread
 * count stay on the REST endpoints, so a client that misses a push (a dropped
 * socket, a replica restart) loses nothing — it re-reads on reconnect.
 */
@Component
public class NotificationSocketHandler extends TextWebSocketHandler {

    private static final Logger log = LoggerFactory.getLogger(NotificationSocketHandler.class);
    private static final int SEND_TIME_LIMIT_MS = 5_000;
    private static final int BUFFER_SIZE_LIMIT_BYTES = 256 * 1024;

    private final Map<String, ConnectedInbox> inboxes = new ConcurrentHashMap<>();
    private final ObjectMapper objectMapper;
    private final NotificationRepository notifications;

    public NotificationSocketHandler(ObjectMapper objectMapper, NotificationRepository notifications) {
        this.objectMapper = objectMapper;
        this.notifications = notifications;
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        Map<String, Object> attributes = session.getAttributes();
        // Pushes come from channel and Redis threads; the decorator serializes
        // concurrent sends to one session.
        WebSocketSession safe = new ConcurrentWebSocketSessionDecorator(
            session, SEND_TIME_LIMIT_MS, BUFFER_SIZE_LIMIT_BYTES);
        inboxes.put(session.getId(), new ConnectedInbox(
            safe, (Integer) attributes.get(NotificationHandshakeInterceptor.USER_ID)));
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        inboxes.remove(session.getId());
    }

    @Override
    public void handleTransportError(WebSocketSession session, Throwable exception) {
        inboxes.remove(session.getId());
    }

    /**
     * Push to every socket on this replica whose user may receive the event
     * now. One query per push decides that for all users connected here.
     */
    public void deliverLocally(NotificationEvent event) {
        if (inboxes.isEmpty()) {
            return;
        }
        Set<Integer> connected = new HashSet<>();
        inboxes.values().forEach(inbox -> connected.add(inbox.userId()));
        Set<Integer> addressed;
        try {
            List<Integer> allowed = notifications.findAddressedActiveUsers(event.notificationId(), connected);
            addressed = new HashSet<>(allowed);
        } catch (RuntimeException e) {
            log.warn("notification push skipped: recipient check failed", e);
            return;
        }
        if (addressed.isEmpty()) {
            return;
        }
        String frame;
        try {
            frame = objectMapper.writeValueAsString(Map.of(
                "event", "notification",
                "notification", event.notification()));
        } catch (JsonProcessingException e) {
            log.warn("notification push could not be serialized", e);
            return;
        }
        TextMessage message = new TextMessage(frame);
        for (ConnectedInbox inbox : inboxes.values()) {
            if (!addressed.contains(inbox.userId())) {
                continue;
            }
            try {
                inbox.session().sendMessage(message);
            } catch (IOException | RuntimeException e) {
                log.debug("notification push to session {} failed", inbox.session().getId(), e);
            }
        }
    }

    /** Open notification sockets on this replica. */
    int connectedCount() {
        return inboxes.size();
    }
}
