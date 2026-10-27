package de.tum.cit.aet.logos.logoswebservice.orchestrator;

import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

/**
 * Asks the orchestrator's secret-gated /internal/hf_reachability whether the
 * central HF_TOKEN can see a Hugging Face model repository. The normalized
 * provider/model name of a model request is the repository id, so a request
 * may only be recorded when the verdict is {@code reachable}.
 *
 * The orchestrator itself never fails the check: {@code rejected} is a
 * verdict from the Hub, {@code unknown} means the Hub could not be asked. A
 * transport failure on this side (orchestrator not configured or unreachable,
 * timeout, unparsable answer) is reported as {@code unknown} as well, so
 * callers branch on exactly two outcomes and the round trip never fails the
 * request itself.
 */
@Service
public class OrchestratorHfReachabilityClient {

    private static final Logger log = LoggerFactory.getLogger(OrchestratorHfReachabilityClient.class);
    private static final ObjectMapper JSON = new ObjectMapper();

    private final RestTemplate restTemplate;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    @Value("${logos.orchestrator.internal-secret:}")
    private String internalSecret;

    public OrchestratorHfReachabilityClient(@Qualifier("hfReachabilityRestTemplate") RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /** The orchestrator's verdict for one repository id. Never null. */
    public record HfReachabilityResult(String status, String reasonCode, String detail) {
        public static final String STATUS_REACHABLE = "reachable";
        public static final String STATUS_REJECTED = "rejected";
        public static final String STATUS_UNKNOWN = "unknown";
        /** Reason code the orchestrator answers with when the repository is gated. */
        public static final String REASON_MODEL_GATED = "model-gated";

        public static HfReachabilityResult unknown(String detail) {
            return new HfReachabilityResult(STATUS_UNKNOWN, null, detail);
        }
    }

    /**
     * Whether the central HF_TOKEN can see the repository. Any failure short
     * of the Hub's answer is {@code unknown} — not a verdict about the
     * repository, so callers must not treat or store it as one.
     */
    public HfReachabilityResult check(String hfRepoId) {
        if (orchestratorUrl.isBlank() || internalSecret == null || internalSecret.isBlank()) {
            return HfReachabilityResult.unknown("The orchestrator is not configured.");
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("Authorization", "Bearer " + internalSecret);
            var response = restTemplate.exchange(
                orchestratorUrl + "/internal/hf_reachability",
                HttpMethod.POST,
                new HttpEntity<>(JSON.writeValueAsString(Map.of("hf_repo_id", hfRepoId)), headers),
                Map.class);
            return toResult(response.getBody());
        } catch (Exception e) {
            // Library/network errors can name internal hosts or proxies; log only.
            log.warn("HF reachability check for {} failed: {}", hfRepoId, e.getMessage());
            return HfReachabilityResult.unknown("The model could not be checked right now.");
        }
    }

    /** Reduce the answer to the public fields; a missing status is unknown. */
    private static HfReachabilityResult toResult(Object body) {
        if (!(body instanceof Map<?, ?> map)) {
            return HfReachabilityResult.unknown("The reachability answer carried no status.");
        }
        String status = map.get("status") instanceof String s ? s : null;
        if (status == null) {
            return HfReachabilityResult.unknown("The reachability answer carried no status.");
        }
        String reasonCode = map.get("reason_code") instanceof String r ? r : null;
        String detail = map.get("detail") instanceof String d ? d : null;
        return new HfReachabilityResult(status, reasonCode, detail);
    }
}
