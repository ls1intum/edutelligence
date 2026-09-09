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
        notifyRefresh(rebuildClassifier, false);
    }

    /**
     * Announce a pipeline refresh to the orchestrator.
     *
     * @param rebuildClassifier whether the model classifier has to be rebuilt
     * @param syncCloudModels   whether a cloud provider itself was added or changed. A new provider
     *                          contributes no models until its {@code /v1/models} listing is read, and
     *                          that otherwise waits for the orchestrator's 15-minute interval — long
     *                          enough that an operator reads the empty list as a broken sync. The
     *                          orchestrator schedules the pass and answers immediately, so this stays
     *                          as cheap as a plain refresh.
     */
    @Async
    public void notifyRefresh(boolean rebuildClassifier, boolean syncCloudModels) {
        if (orchestratorUrl.isBlank() || internalSecret.isBlank()) {
            return;
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("Authorization", "Bearer " + internalSecret);
            headers.set("Content-Type", "application/json");
            HttpEntity<Map<String, Object>> request = new HttpEntity<>(
                Map.of("rebuild_classifier", rebuildClassifier, "sync_cloud_models", syncCloudModels), headers
            );
            restTemplate.postForEntity(orchestratorUrl + "/internal/refresh_pipeline", request, Void.class);
        } catch (Exception e) {
            log.warn("Failed to notify orchestrator of pipeline refresh: {}", e.getMessage());
        }
    }
}
