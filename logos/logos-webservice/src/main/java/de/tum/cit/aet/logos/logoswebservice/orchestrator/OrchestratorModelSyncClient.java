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
     * The cloud model sync's in-flight state: true while a pass is running
     * or queued, false once the orchestrator explicitly reports none in
     * flight, and null when the state could not be read. The null matters:
     * the admin UI treats an accepted refresh as settled only on an explicit
     * false, so a transient timeout or a rolling-deploy 404 reads as unknown
     * — and the UI keeps polling within its cap — rather than as "done". No
     * caching: the UI polls on a two-second cadence and a stale "running"
     * would keep its spinner spinning.
     */
    public Boolean isSyncRunning() {
        if (orchestratorUrl.isBlank() || internalSecret == null || internalSecret.isBlank()) {
            return null;
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("Authorization", "Bearer " + internalSecret);
            var response = restTemplate.exchange(
                orchestratorUrl + "/internal/cloud_model_sync_status",
                HttpMethod.GET,
                new HttpEntity<Void>(headers),
                Map.class);
            if (response.getBody() instanceof Map<?, ?> body && body.get("running") instanceof Boolean running) {
                return running;
            }
            return null;
        } catch (Exception e) {
            log.warn("Failed to fetch cloud model sync status from orchestrator: {}", e.getMessage());
            return null;
        }
    }
}
