package de.tum.cit.aet.logos.logoswebservice.websocket;

import java.time.LocalDate;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.VramService;

@Component
public class StatsPoller {

    private final VramService vramService;
    private final RequestLogService requestLogService;
    private final ObjectMapper objectMapper;

    public StatsPoller(VramService vramService, RequestLogService requestLogService,
                       ObjectMapper objectMapper) {
        this.vramService = vramService;
        this.requestLogService = requestLogService;
        this.objectMapper = objectMapper;
    }

    public String buildVramMessage(String day) {
        try {
            String effectiveDay = (day != null && !day.isBlank()) ? day : LocalDate.now().toString();
            Map<String, Object> payload = vramService.getVramStats(effectiveDay);
            return objectMapper.writeValueAsString(Map.of("type", "vram", "payload", payload));
        } catch (Exception e) {
            return "{\"type\":\"vram\",\"payload\":{\"providers\":[]}}";
        }
    }

    public String buildRequestsMessage() {
        try {
            Map<String, Object> payload = requestLogService.getLatestRequests();
            return objectMapper.writeValueAsString(Map.of("type", "requests", "payload", payload));
        } catch (Exception e) {
            return "{\"type\":\"requests\",\"payload\":{\"requests\":[]}}";
        }
    }

    public String buildSnapshot() {
        return buildRequestsMessage();
    }
}
