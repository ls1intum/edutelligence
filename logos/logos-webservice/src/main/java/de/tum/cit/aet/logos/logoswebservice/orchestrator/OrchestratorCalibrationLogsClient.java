package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * Fetches every node's most recent calibration probe log for one model from
 * the orchestrator. Backs the model-error-report page's "Complete Logs"
 * tab. Unlike {@link OrchestratorModelWindowClient}, this is not cached —
 * it's only fetched when a user opens one model's error-report page, not on
 * every model-listing render, and callers want current calibration state.
 */
@Service
public class OrchestratorCalibrationLogsClient {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorCalibrationLogsClient.class);

    private final RestTemplate restTemplate;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    public OrchestratorCalibrationLogsClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * Calibration probe log rows for {@code modelName}, one per provider
     * that has calibrated it. Returns an empty list (never throws) when the
     * orchestrator is unreachable or unconfigured, so the error-report page
     * never fails to load on this account.
     */
    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> getLogs(String modelName) {
        if (orchestratorUrl.isBlank() || internalSecret.isBlank() || modelName == null || modelName.isBlank()) {
            return List.of();
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("Authorization", "Bearer " + internalSecret);
            String url = UriComponentsBuilder
                .fromUriString(orchestratorUrl + "/internal/calibration_probe_logs")
                .queryParam("model_name", modelName)
                .toUriString();
            var response = restTemplate.exchange(
                url,
                HttpMethod.GET,
                new HttpEntity<Void>(headers),
                Map.class);
            Object raw = response.getBody() != null ? response.getBody().get("logs") : null;
            if (raw instanceof List<?> logs) {
                return (List<Map<String, Object>>) logs;
            }
        } catch (Exception e) {
            log.warn("Failed to fetch calibration probe logs for model {} from orchestrator: {}", modelName, e.getMessage());
        }
        return List.of();
    }
}
