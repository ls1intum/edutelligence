package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.RestTemplate;

@Service
public class OrchestratorWorkerAdminClient {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorWorkerAdminClient.class);

    private final RestTemplate restTemplate;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    public OrchestratorWorkerAdminClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    public ResponseEntity<Map> calibrateUncalibrated(int providerId) {
        return post("/internal/logosnode/calibrate_uncalibrated", Map.of("provider_id", providerId));
    }

    public ResponseEntity<Map> deleteLane(int providerId, String laneId) {
        return post("/internal/logosnode/lanes/delete", Map.of("provider_id", providerId, "lane_id", laneId));
    }

    private ResponseEntity<Map> post(String path, Map<String, Object> body) {
        if (orchestratorUrl.isBlank() || internalSecret.isBlank()) {
            throw new IllegalStateException("Orchestrator URL or internal secret not configured");
        }
        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "Bearer " + internalSecret);
        headers.set("Content-Type", "application/json");
        try {
            return restTemplate.postForEntity(
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
