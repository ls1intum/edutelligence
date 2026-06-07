package de.tum.cit.aet.logos.logoswebservice.websocket;

import java.io.IOException;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.VramService;
import jakarta.annotation.PreDestroy;

@Component
public class StatsWebSocketHandler extends TextWebSocketHandler {

    private static final Logger log = LoggerFactory.getLogger(StatsWebSocketHandler.class);

    private static class SessionState {
        String vramDay = null;
        String prevVramSig = "";
        String prevReqSig = "";
    }

    private final Map<String, WebSocketSession> sessions = new ConcurrentHashMap<>();
    private final Map<String, SessionState> states = new ConcurrentHashMap<>();

    private final VramService vramService;
    private final RequestLogService requestLogService;
    private final ObjectMapper objectMapper;
    private final ScheduledExecutorService scheduler;
    private final AtomicInteger tick = new AtomicInteger(0);

    public StatsWebSocketHandler(VramService vramService,
                                 RequestLogService requestLogService,
                                 ObjectMapper objectMapper) {
        this.vramService = vramService;
        this.requestLogService = requestLogService;
        this.objectMapper = objectMapper;
        this.scheduler = Executors.newSingleThreadScheduledExecutor();
        this.scheduler.scheduleAtFixedRate(this::broadcast, 0, 1, TimeUnit.SECONDS);
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) throws Exception {
        sessions.put(session.getId(), session);
        SessionState state = new SessionState();
        states.put(session.getId(), state);

        Map<String, Object> vramPayload = vramService.getVramStats(null);
        Map<String, Object> reqPayload = requestLogService.getLatestRequests();
        state.prevVramSig = vramSig(vramPayload);
        state.prevReqSig = requestsSig(reqPayload);
        send(session, Map.of("type", "vram", "payload", vramPayload));
        send(session, Map.of("type", "requests", "payload", reqPayload));

        log.debug("[ws/stats] Client connected ({} total)", sessions.size());
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        sessions.remove(session.getId());
        states.remove(session.getId());
        log.debug("[ws/stats] Client disconnected ({} remaining)", sessions.size());
    }

    @Override
    @SuppressWarnings("unchecked")
    protected void handleTextMessage(WebSocketSession session, TextMessage message) {
        SessionState state = states.get(session.getId());
        if (state == null) return;

        Map<String, Object> msg;
        try { msg = objectMapper.readValue(message.getPayload(), Map.class); }
        catch (Exception e) { return; }

        String action = (String) msg.get("action");
        if ("set_vram_day".equals(action)) {
            Object dayObj = msg.get("day");
            if (dayObj instanceof String s && !s.isBlank()) {
                state.vramDay = s;
                state.prevVramSig = ""; 
                try {
                    Map<String, Object> payload = vramService.getVramStats(state.vramDay);
                    state.prevVramSig = vramSig(payload);
                    send(session, Map.of("type", "vram", "payload", payload));
                } catch (Exception e) {
                    log.warn("[ws/stats] VRAM push error on set_vram_day: {}", e.getMessage());
                }
            }
        } else if ("ping".equals(action)) {
            send(session, Map.of("type", "pong"));
        }
    }

    private void broadcast() {
        if (sessions.isEmpty()) return;
        int t = tick.getAndIncrement();

        Map<String, Object> reqPayload = null;
        String reqSig = null;
        try {
            reqPayload = requestLogService.getLatestRequests();
            reqSig = requestsSig(reqPayload);
        } catch (Exception e) {
            log.warn("[ws/stats] Requests push error: {}", e.getMessage());
        }

        boolean buildVram = (t % 5 == 0);

        for (Map.Entry<String, WebSocketSession> entry : sessions.entrySet()) {
            WebSocketSession session = entry.getValue();
            SessionState state = states.get(entry.getKey());
            if (state == null) continue;
            if (!session.isOpen()) {
                sessions.remove(entry.getKey());
                states.remove(entry.getKey());
                continue;
            }

            if (reqPayload != null && reqSig != null && !reqSig.equals(state.prevReqSig)) {
                state.prevReqSig = reqSig;
                send(session, Map.of("type", "requests", "payload", reqPayload));
            }

            if (buildVram) {
                try {
                    Map<String, Object> vramPayload = vramService.getVramStats(state.vramDay);
                    String sig = vramSig(vramPayload);
                    if (!sig.equals(state.prevVramSig)) {
                        state.prevVramSig = sig;
                        send(session, Map.of("type", "vram", "payload", vramPayload));
                    }
                } catch (Exception e) {
                    log.warn("[ws/stats] VRAM push error: {}", e.getMessage());
                }
            }
        }
    }

    @SuppressWarnings("unchecked")
    private String requestsSig(Map<String, Object> payload) {
        List<Map<String, Object>> reqs =
            (List<Map<String, Object>>) payload.getOrDefault("requests", List.of());
        StringBuilder sb = new StringBuilder();
        for (var r : reqs) {
            sb.append(r.getOrDefault("request_id", "")).append(':')
              .append(r.getOrDefault("status", "")).append(':')
              .append(r.getOrDefault("scheduled_ts", "")).append(':')
              .append(r.getOrDefault("request_complete_ts", "")).append(',');
        }
        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    private String vramSig(Map<String, Object> payload) {
        List<Map<String, Object>> providers =
            (List<Map<String, Object>>) payload.getOrDefault("providers", List.of());
        StringBuilder sb = new StringBuilder();
        providers.stream()
            .sorted(Comparator.comparing(p -> String.valueOf(p.getOrDefault("name", ""))))
            .forEach(p -> {
                List<Map<String, Object>> data =
                    (List<Map<String, Object>>) p.getOrDefault("data", List.of());
                Map<String, Object> last = data.isEmpty() ? Map.of() : data.get(data.size() - 1);
                sb.append(p.getOrDefault("name", "")).append("::")
                  .append(last.getOrDefault("timestamp", "")).append("::")
                  .append(last.getOrDefault("used_vram_mb", "")).append("::")
                  .append(last.getOrDefault("remaining_vram_mb", "")).append("::")
                  .append(last.getOrDefault("total_vram_mb", "")).append("||");
            });
        return sb.toString();
    }

    private void send(WebSocketSession session, Object payload) {
        try {
            String json = objectMapper.writeValueAsString(payload);
            synchronized (session) {
                if (session.isOpen()) session.sendMessage(new TextMessage(json));
            }
        } catch (IOException e) {
            sessions.remove(session.getId());
            states.remove(session.getId());
        }
    }

    @PreDestroy
    public void shutdown() {
        scheduler.shutdownNow();
    }
}
