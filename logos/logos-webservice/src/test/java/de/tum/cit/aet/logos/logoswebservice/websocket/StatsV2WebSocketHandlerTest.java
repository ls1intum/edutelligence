package de.tum.cit.aet.logos.logoswebservice.websocket;

import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.jdbc.Sql;
import org.springframework.test.context.jdbc.SqlMergeMode;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

@SpringBootTest
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml"
})
@Sql(scripts = {"/sql/seed-identity.sql", "/sql/seed-configuration.sql", "/sql/seed-operations.sql"},
     executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
@Sql(scripts = {"/sql/cleanup-operations.sql", "/sql/cleanup-configuration.sql", "/sql/cleanup-identity.sql"},
     executionPhase = Sql.ExecutionPhase.AFTER_TEST_METHOD)
class StatsV2WebSocketHandlerTest {

    @Autowired
    StatsV2WebSocketHandler handler;
    @Autowired
    ObjectMapper objectMapper;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void handlerIsWired() {
        assertThat(handler).isNotNull();
    }

    @Test
    void ping_returnsPong() throws Exception {
        WebSocketSession session = mock(WebSocketSession.class);
        when(session.getId()).thenReturn("test-v2-ping-session");
        when(session.isOpen()).thenReturn(true);

        handler.afterConnectionEstablished(session);
        handler.handleMessage(session, new TextMessage("{\"action\":\"ping\"}"));

        ArgumentCaptor<TextMessage> captor = ArgumentCaptor.forClass(TextMessage.class);
        verify(session).sendMessage(captor.capture());
        assertThat(captor.getValue().getPayload()).contains("\"type\":\"pong\"");

        handler.afterConnectionClosed(session, CloseStatus.NORMAL);
    }

    @Test
    @SqlMergeMode(SqlMergeMode.MergeMode.MERGE)
    @Sql(scripts = {"/sql/seed-operations-status.sql"}, executionPhase = Sql.ExecutionPhase.BEFORE_TEST_METHOD)
    void setFeedStatus_narrowsTheRequestPushAndReportsTheBucketTotal() throws Exception {
        // One row per lifecycle bucket plus the shared seed's two finished rows.
        WebSocketSession session = mock(WebSocketSession.class);
        when(session.getId()).thenReturn("test-v2-feed-status-session");
        when(session.isOpen()).thenReturn(true);

        handler.afterConnectionEstablished(session);
        handler.handleMessage(session, new TextMessage("{\"action\":\"init\"}"));

        // The unfiltered init push carries every row and no total — the page
        // borrows the statistics aggregate for its "of N" figure.
        List<TextMessage> sent = captureRequestsPushes(session);
        JsonNode first = requestsPayload(sent);
        assertThat(first.get("requests").size()).isEqualTo(6);
        assertThat(first.has("total")).isFalse();

        // Narrowing the feed re-pushes only the bucket and counts it: the
        // aggregate the page borrows is only as narrow as the team/user scope,
        // so a filtered feed must say how big its own bucket is.
        handler.handleMessage(session, new TextMessage("{\"action\":\"set_feed_status\",\"status\":\"queued\"}"));
        sent = captureRequestsPushes(session);
        JsonNode queued = requestsPayload(sent);
        assertThat(queued.get("requests").size()).isEqualTo(1);
        assertThat(queued.get("requests").get(0).get("request_id").asText()).isEqualTo("req-state-queued");
        assertThat(queued.get("total").asLong()).isEqualTo(1L);

        handler.handleMessage(session, new TextMessage("{\"action\":\"set_feed_status\",\"status\":\"finished\"}"));
        sent = captureRequestsPushes(session);
        JsonNode finished = requestsPayload(sent);
        assertThat(finished.get("requests").size()).isEqualTo(3);
        assertThat(finished.get("total").asLong()).isEqualTo(3L);

        // Clearing the filter goes back to the full feed and drops the total,
        // handing the "of N" figure back to the statistics aggregate.
        handler.handleMessage(session, new TextMessage("{\"action\":\"set_feed_status\",\"status\":null}"));
        sent = captureRequestsPushes(session);
        JsonNode cleared = requestsPayload(sent);
        assertThat(cleared.get("requests").size()).isEqualTo(6);
        assertThat(cleared.has("total")).isFalse();

        handler.afterConnectionClosed(session, CloseStatus.NORMAL);
    }

    /** Every requests push the session has been sent so far, in order. */
    private List<TextMessage> captureRequestsPushes(WebSocketSession session) throws Exception {
        ArgumentCaptor<TextMessage> captor = ArgumentCaptor.forClass(TextMessage.class);
        verify(session, atLeastOnce()).sendMessage(captor.capture());
        return captor.getAllValues().stream()
            .filter(m -> m.getPayload().contains("\"type\":\"requests\""))
            .toList();
    }

    private JsonNode requestsPayload(List<TextMessage> pushes) throws Exception {
        assertThat(pushes).as("a requests push was sent").isNotEmpty();
        return objectMapper.readTree(pushes.get(pushes.size() - 1).getPayload()).get("payload");
    }
}
