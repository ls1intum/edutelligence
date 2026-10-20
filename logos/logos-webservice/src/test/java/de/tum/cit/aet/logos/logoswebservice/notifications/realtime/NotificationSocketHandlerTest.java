package de.tum.cit.aet.logos.logoswebservice.notifications.realtime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.notifications.repository.NotificationRepository;

/**
 * Which open sockets a push reaches: exactly the connected users the
 * database says are addressed right now (the recipient check is the
 * repository's; it is pinned against a real database in NotificationServiceTest).
 */
class NotificationSocketHandlerTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final NotificationRepository notifications = mock(NotificationRepository.class);
    private final NotificationSocketHandler handler = new NotificationSocketHandler(objectMapper, notifications);

    private WebSocketSession connect(String id, int userId) {
        WebSocketSession session = mock(WebSocketSession.class);
        Map<String, Object> attributes = new HashMap<>();
        attributes.put(NotificationHandshakeInterceptor.USER_ID, userId);
        when(session.getId()).thenReturn(id);
        when(session.getAttributes()).thenReturn(attributes);
        when(session.isOpen()).thenReturn(true);
        handler.afterConnectionEstablished(session);
        return session;
    }

    private static NotificationEvent event(long id) {
        return new NotificationEvent(id, Map.of("id", id, "title", "Hello"));
    }

    @Test
    void pushesOnlyToUsersTheDatabaseAddresses() throws Exception {
        WebSocketSession addressed = connect("a", 1001);
        WebSocketSession secondTab = connect("b", 1001);
        WebSocketSession other = connect("c", 1006);
        when(notifications.findAddressedActiveUsers(eq(7L), anyCollection())).thenReturn(List.of(1001));

        handler.deliverLocally(event(7));

        verify(addressed).sendMessage(any());
        verify(secondTab).sendMessage(any());
        verify(other, never()).sendMessage(any());
    }

    @Test
    void framesTheNotificationAsAnEvent() throws Exception {
        WebSocketSession session = connect("a", 1001);
        when(notifications.findAddressedActiveUsers(eq(7L), anyCollection())).thenReturn(List.of(1001));
        handler.deliverLocally(event(7));

        ArgumentCaptor<TextMessage> frame = ArgumentCaptor.forClass(TextMessage.class);
        verify(session).sendMessage(frame.capture());
        Map<?, ?> body = objectMapper.readValue(frame.getValue().getPayload(), Map.class);
        assertThat(body.get("event")).isEqualTo("notification");
        assertThat(((Map<?, ?>) body.get("notification")).get("title")).isEqualTo("Hello");
    }

    @Test
    void noOpenSocketsMeansNoRecipientQuery() {
        handler.deliverLocally(event(7));
        verifyNoInteractions(notifications);
    }

    @Test
    void closedSocketsAreForgotten() throws Exception {
        WebSocketSession session = connect("a", 1001);
        handler.afterConnectionClosed(session, CloseStatus.NORMAL);
        assertThat(handler.connectedCount()).isZero();

        handler.deliverLocally(event(7));
        verify(session, never()).sendMessage(any());
    }

    @Test
    void aFailedRecipientCheckSendsNothing() throws Exception {
        WebSocketSession session = connect("a", 1001);
        when(notifications.findAddressedActiveUsers(eq(7L), anyCollection())).thenThrow(new IllegalStateException("db down"));
        handler.deliverLocally(event(7));
        verify(session, never()).sendMessage(any());
    }

    @Test
    void fanoutEventSurvivesTheRedisJsonRoundTrip() throws Exception {
        NotificationEvent sent = event(7);
        NotificationEvent received = objectMapper.readValue(objectMapper.writeValueAsString(sent), NotificationEvent.class);
        assertThat(received.notificationId()).isEqualTo(7L);
        assertThat(received.notification()).containsEntry("title", "Hello");
    }
}
