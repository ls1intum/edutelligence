package de.tum.cit.aet.logos.logoswebservice.notifications.realtime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.notifications.dto.NotificationTargetDTO;

/**
 * Which open sockets a push reaches: the same user/role/team rule as the
 * inbox query, evaluated against the identity captured at the handshake.
 */
class NotificationSocketHandlerTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final NotificationSocketHandler handler = new NotificationSocketHandler(objectMapper);

    private WebSocketSession connect(String id, int userId, String role, Set<Integer> teamIds) {
        WebSocketSession session = mock(WebSocketSession.class);
        Map<String, Object> attributes = new HashMap<>();
        attributes.put(NotificationHandshakeInterceptor.USER_ID, userId);
        attributes.put(NotificationHandshakeInterceptor.ROLE, role);
        attributes.put(NotificationHandshakeInterceptor.TEAM_IDS, teamIds);
        when(session.getId()).thenReturn(id);
        when(session.getAttributes()).thenReturn(attributes);
        when(session.isOpen()).thenReturn(true);
        handler.afterConnectionEstablished(session);
        return session;
    }

    private static NotificationEvent event(NotificationTargetDTO... targets) {
        return new NotificationEvent(Map.of("id", 1, "title", "Hello"), List.of(targets));
    }

    @Test
    void pushesOnlyToAddressedSockets() throws Exception {
        WebSocketSession developer = connect("a", 1001, "app_developer", Set.of(2001));
        WebSocketSession appAdmin = connect("b", 1002, "app_admin", Set.of());
        WebSocketSession other = connect("c", 1006, "app_developer", Set.of(2002));

        handler.deliverLocally(event(new NotificationTargetDTO("team", 2001, null),
                                     new NotificationTargetDTO("role", null, "app_admin")));

        verify(developer).sendMessage(any());
        verify(appAdmin).sendMessage(any());
        verify(other, never()).sendMessage(any());
    }

    @Test
    void userTargetReachesOnlyThatUser() throws Exception {
        WebSocketSession target = connect("a", 1003, "logos_admin", Set.of());
        WebSocketSession bystander = connect("b", 1001, "logos_admin", Set.of());

        handler.deliverLocally(event(new NotificationTargetDTO("user", 1003, null)));

        verify(target).sendMessage(any());
        verify(bystander, never()).sendMessage(any());
    }

    @Test
    void framesTheNotificationAsAnEvent() throws Exception {
        WebSocketSession session = connect("a", 1001, "app_developer", Set.of());
        handler.deliverLocally(event(new NotificationTargetDTO("user", 1001, null)));

        ArgumentCaptor<TextMessage> frame = ArgumentCaptor.forClass(TextMessage.class);
        verify(session).sendMessage(frame.capture());
        Map<?, ?> body = objectMapper.readValue(frame.getValue().getPayload(), Map.class);
        assertThat(body.get("event")).isEqualTo("notification");
        assertThat(((Map<?, ?>) body.get("notification")).get("title")).isEqualTo("Hello");
    }

    @Test
    void closedSocketsAreForgotten() throws Exception {
        WebSocketSession session = connect("a", 1001, "app_developer", Set.of());
        handler.afterConnectionClosed(session, CloseStatus.NORMAL);
        assertThat(handler.connectedCount()).isZero();

        handler.deliverLocally(event(new NotificationTargetDTO("user", 1001, null)));
        verify(session, never()).sendMessage(any());
    }

    @Test
    void fanoutEventSurvivesTheRedisJsonRoundTrip() throws Exception {
        NotificationEvent sent = event(new NotificationTargetDTO("role", null, "app_admin"));
        NotificationEvent received = objectMapper.readValue(objectMapper.writeValueAsString(sent), NotificationEvent.class);
        assertThat(received.targets()).isEqualTo(sent.targets());
        assertThat(received.notification()).containsEntry("title", "Hello");
    }
}
