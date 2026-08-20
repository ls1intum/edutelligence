package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.RestTemplate;

import de.tum.cit.aet.logos.logoswebservice.common.RestTemplateConfig;

@Service
public class OrchestratorWorkerAdminClient {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorWorkerAdminClient.class);

    private final RestTemplate restTemplate;
    // add_lane loads a model and can take minutes on the worker; the shared
    // 5 s read timeout would kill the call long before the worker answers, so
    // long-running commands use the template configured for that in
    // RestTemplateConfig.
    private final RestTemplate longRunningRestTemplate;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    public OrchestratorWorkerAdminClient(
            RestTemplate restTemplate,
            @Qualifier(RestTemplateConfig.LONG_RUNNING) RestTemplate longRunningRestTemplate) {
        this.restTemplate = restTemplate;
        this.longRunningRestTemplate = longRunningRestTemplate;
    }

    public ResponseEntity<Map> calibrateUncalibrated(int providerId) {
        return post("/internal/logosnode/calibrate_uncalibrated", Map.of("provider_id", providerId));
    }

    public ResponseEntity<Map> deleteLane(int providerId, String laneId) {
        return post("/internal/logosnode/lanes/delete", Map.of("provider_id", providerId, "lane_id", laneId));
    }

    public ResponseEntity<Map> addLane(int providerId, Map<String, Object> lane) {
        return post(longRunningRestTemplate,
            "/internal/logosnode/lanes/add", Map.of("provider_id", providerId, "lane", lane));
    }

    private ResponseEntity<Map> post(String path, Map<String, Object> body) {
        return post(restTemplate, path, body);
    }

    private ResponseEntity<Map> post(RestTemplate template, String path, Map<String, Object> body) {
        if (orchestratorUrl.isBlank() || internalSecret.isBlank()) {
            throw new IllegalStateException("Orchestrator URL or internal secret not configured");
        }
        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "Bearer " + internalSecret);
        headers.set("Content-Type", "application/json");
        try {
            return template.postForEntity(
                orchestratorUrl + path,
                new HttpEntity<>(body, headers),
                Map.class
            );
        } catch (HttpClientErrorException | HttpServerErrorException e) {
            log.warn("Orchestrator worker admin call to {} failed: {} {}", path, e.getStatusCode(), e.getResponseBodyAsString());
            throw e;
        }
    }
}
