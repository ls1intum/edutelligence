package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

/**
 * Reads the cloud model sync's in-flight state from the orchestrator's
 * secret-gated /internal/cloud_model_sync_status endpoint. A manual refresh
 * is answered by the orchestrator before its pass has written anything, so
 * the admin UI polls this until the triggered pass reports done; unchanged
 * model lists are not that signal, because the first write of a pass can
 * land at any moment.
 */
@Service
public class OrchestratorModelSyncClient {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorModelSyncClient.class);

    private final RestTemplate restTemplate;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    public OrchestratorModelSyncClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * Whether a cloud model sync pass is running or queued. No caching: the
     * UI polls this on a two-second cadence and a stale "running" would keep
     * its spinner spinning. Any failure — including an orchestrator without
     * the endpoint yet — degrades to "not running", so a missing status can
     * only end the wait early, never hold it open.
     */
    public boolean isSyncRunning() {
        if (orchestratorUrl.isBlank() || internalSecret == null || internalSecret.isBlank()) {
            return false;
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("Authorization", "Bearer " + internalSecret);
            var response = restTemplate.exchange(
                orchestratorUrl + "/internal/cloud_model_sync_status",
                HttpMethod.GET,
                new HttpEntity<Void>(headers),
                Map.class);
            return response.getBody() instanceof Map<?, ?> body && Boolean.TRUE.equals(body.get("running"));
        } catch (Exception e) {
            log.warn("Failed to fetch cloud model sync status from orchestrator: {}", e.getMessage());
            return false;
        }
    }
}
