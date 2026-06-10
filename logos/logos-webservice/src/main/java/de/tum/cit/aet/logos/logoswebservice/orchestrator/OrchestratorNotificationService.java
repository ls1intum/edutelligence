package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Service
public class OrchestratorNotificationService {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorNotificationService.class);

    private final RestTemplate restTemplate;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    public OrchestratorNotificationService(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    @Async
    public void notifyRefresh(boolean rebuildClassifier) {
        if (orchestratorUrl.isBlank() || internalSecret.isBlank()) {
            return;
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("Authorization", "Bearer " + internalSecret);
            headers.set("Content-Type", "application/json");
            HttpEntity<Map<String, Object>> request = new HttpEntity<>(
                Map.of("rebuild_classifier", rebuildClassifier), headers
            );
            restTemplate.postForEntity(orchestratorUrl + "/internal/refresh_pipeline", request, Void.class);
        } catch (Exception e) {
            log.warn("Failed to notify orchestrator of pipeline refresh: {}", e.getMessage());
        }
    }
}
