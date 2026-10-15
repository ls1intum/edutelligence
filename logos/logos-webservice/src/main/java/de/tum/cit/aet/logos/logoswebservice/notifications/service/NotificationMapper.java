package de.tum.cit.aet.logos.logoswebservice.notifications.service;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.notifications.dto.NotificationResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.notifications.entity.Notification;

/** One rendering of a notification for the inbox endpoints and the socket push. */
@Component
public class NotificationMapper {

    private final ObjectMapper objectMapper;

    public NotificationMapper(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public NotificationResponseDTO toDto(Notification n, boolean read) {
        Object payload = null;
        if (n.getPayload() != null && !n.getPayload().isBlank()) {
            try {
                payload = objectMapper.readValue(n.getPayload(), Object.class);
            } catch (Exception e) {
                // The payload is written by us as valid JSON, so this is
                // defensive; fall back to the raw text rather than dropping it.
                payload = n.getPayload();
            }
        }
        return new NotificationResponseDTO(
            n.getId(),
            n.getType().name(),
            n.getTitle(),
            n.getBody(),
            payload,
            n.getSource(),
            n.getActorUserId(),
            n.getCreatedAt(),
            read);
    }

    /**
     * The same item in the inbox endpoints' snake_case JSON shape, for the
     * socket push (which does not go through the HTTP message converters).
     */
    public Map<String, Object> toWire(NotificationResponseDTO dto) {
        Map<String, Object> wire = new LinkedHashMap<>();
        wire.put("id", dto.id());
        wire.put("type", dto.type());
        wire.put("title", dto.title());
        wire.put("body", dto.body());
        wire.put("payload", dto.payload());
        wire.put("source", dto.source());
        wire.put("actor_user_id", dto.actorUserId());
        wire.put("created_at", dto.createdAt() == null ? null : dto.createdAt().toString());
        wire.put("read", dto.read());
        return wire;
    }
}
