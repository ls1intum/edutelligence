package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestTemplate;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;

import jakarta.annotation.PostConstruct;

/**
 * The batch pages, served by talking to the orchestrator as the user's own key.
 *
 * The webservice deliberately does not write batch rows itself. Everything that
 * makes a batch safe — the key's model permissions checked line by line, the
 * ownership of the ids, the budget guard, the choice between forwarding to a
 * provider and running the job here — lives in the orchestrator's Batch API. A
 * second implementation in Java would be a second set of those rules to keep in
 * step, so this forwards to the same endpoints a script would call, with the
 * API key the user picked in the UI.
 *
 * The key is the user's secret, so where it may travel is checked at startup
 * (HTTPS, or plain HTTP on loopback for local development) and the template
 * used never follows a redirect that could carry it to another authority.
 */
@Service
public class BatchService {

    private static final Logger log = LoggerFactory.getLogger(BatchService.class);

    private final RestTemplate restTemplate;
    private final ApiKeyRepository apiKeyRepository;

    @Value("${logos.orchestrator.url:}")
    private String orchestratorUrl;

    public BatchService(@Qualifier("batchRestTemplate") RestTemplate restTemplate, ApiKeyRepository apiKeyRepository) {
        this.restTemplate = restTemplate;
        this.apiKeyRepository = apiKeyRepository;
    }

    /**
     * The batch proxy sends the caller's API key to this URL on every call, so
     * a URL that would put the key on the wire in cleartext is a
     * misconfiguration that should fail the deployment, not the request.
     * HTTPS is fine anywhere; plain HTTP only on loopback, matching the
     * orchestrator's own rule for credentials.
     */
    @PostConstruct
    void validateOrchestratorUrl() {
        if (orchestratorUrl.isBlank()) return;
        URI uri;
        try {
            uri = URI.create(orchestratorUrl);
        } catch (IllegalArgumentException exc) {
            throw new IllegalStateException("logos.orchestrator.url is not a valid URL: " + orchestratorUrl, exc);
        }
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        String host = uri.getHost() == null ? "" : uri.getHost().toLowerCase(Locale.ROOT);
        boolean loopback = "localhost".equals(host) || "127.0.0.1".equals(host) || "::1".equals(host);
        if ("https".equals(scheme) || ("http".equals(scheme) && loopback)) return;
        throw new IllegalStateException(
            "The batch proxy sends the caller's API key to logos.orchestrator.url ("
                + orchestratorUrl
                + "), which is not HTTPS. Point it at an HTTPS endpoint (plain HTTP is only accepted on loopback) "
                + "so the key does not travel in cleartext.");
    }

    /** Raised when the caller may not act as the key they named. */
    public static class KeyNotOwnedException extends RuntimeException {
        public KeyNotOwnedException(String message) {
            super(message);
        }
    }

    /** An orchestrator answer, passed back to the browser as it came. */
    public record ProxiedResponse(int status, String contentType, byte[] body) {
    }

    /**
     * The user's active keys, as the batch page's key picker needs them.
     *
     * A batch runs as one key: its permissions decide which models the file may
     * name and its team owns the resulting objects.
     */
    public List<Map<String, Object>> keysForUser(int userId) {
        return apiKeyRepository.findByUserIdAndIsActiveTrueOrderByIdAsc(userId).stream()
            .map(key -> {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("id", key.getId());
                entry.put("name", key.getName());
                entry.put("team_id", key.getTeamId());
                entry.put("environment", key.getEnvironment());
                return entry;
            })
            .toList();
    }

    /**
     * The key's secret, once the caller is confirmed to own it.
     *
     * The UI never sees this value: it names a key by id, and the ownership
     * check here is what stops one user from submitting work as another's key.
     */
    private String keyValueOwnedBy(int userId, int apiKeyId) {
        ApiKey key = apiKeyRepository.findById(apiKeyId).orElse(null);
        if (key == null || !Boolean.TRUE.equals(key.getIsActive())
                || key.getUserId() == null || key.getUserId() != userId) {
            throw new KeyNotOwnedException("This API key does not belong to you.");
        }
        return key.getKeyValue();
    }

    public ProxiedResponse listBatches(int userId, int apiKeyId) {
        return call(userId, apiKeyId, HttpMethod.GET, "/v1/batches", null, null);
    }

    public ProxiedResponse getBatch(int userId, int apiKeyId, String batchId) {
        return call(userId, apiKeyId, HttpMethod.GET, "/v1/batches/" + batchId, null, null);
    }

    public ProxiedResponse cancelBatch(int userId, int apiKeyId, String batchId) {
        return call(userId, apiKeyId, HttpMethod.POST, "/v1/batches/" + batchId + "/cancel", null, null);
    }

    /** The result file of a finished batch, streamed back to the browser. */
    public ProxiedResponse batchResults(int userId, int apiKeyId, String outputFileId) {
        return call(userId, apiKeyId, HttpMethod.GET, "/v1/files/" + outputFileId + "/content", null, null);
    }

    /**
     * Upload a JSONL file and start a batch from it.
     *
     * Two calls, exactly as a script would make them: the file first (which is
     * where the per-line permission check happens and where Logos decides
     * whether a provider can run this batch), then the batch itself.
     */
    public ProxiedResponse createBatch(int userId, int apiKeyId, String filename, byte[] content,
                                       String endpoint, String completionWindow, String execution) {
        String keyValue = keyValueOwnedBy(userId, apiKeyId);

        MultiValueMap<String, Object> form = new LinkedMultiValueMap<>();
        ByteArrayResource file = new ByteArrayResource(content) {
            @Override
            public String getFilename() {
                return filename != null && !filename.isBlank() ? filename : "batch.jsonl";
            }
        };
        form.add("file", file);
        form.add("purpose", "batch");

        HttpHeaders uploadHeaders = headers(keyValue, execution);
        uploadHeaders.setContentType(MediaType.MULTIPART_FORM_DATA);
        ProxiedResponse uploaded = exchange(HttpMethod.POST, "/v1/files", new HttpEntity<>(form, uploadHeaders));
        if (uploaded.status() >= 400) {
            return uploaded;
        }
        String fileId = readId(uploaded);
        if (fileId == null) {
            return new ProxiedResponse(502, MediaType.APPLICATION_JSON_VALUE,
                "{\"error\":{\"message\":\"The upload returned no file id.\"}}".getBytes(StandardCharsets.UTF_8));
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("input_file_id", fileId);
        body.put("endpoint", endpoint != null && !endpoint.isBlank() ? endpoint : "/v1/chat/completions");
        body.put("completion_window", completionWindow != null && !completionWindow.isBlank()
            ? completionWindow : "24h");

        HttpHeaders createHeaders = headers(keyValue, execution);
        createHeaders.setContentType(MediaType.APPLICATION_JSON);
        return exchange(HttpMethod.POST, "/v1/batches", new HttpEntity<>(body, createHeaders));
    }

    private ProxiedResponse call(int userId, int apiKeyId, HttpMethod method, String path,
                                 Object body, MediaType contentType) {
        HttpHeaders requestHeaders = headers(keyValueOwnedBy(userId, apiKeyId), null);
        if (contentType != null) {
            requestHeaders.setContentType(contentType);
        }
        return exchange(method, path, new HttpEntity<>(body, requestHeaders));
    }

    private HttpHeaders headers(String keyValue, String execution) {
        HttpHeaders requestHeaders = new HttpHeaders();
        requestHeaders.set("logos_key", keyValue);
        if (execution != null && !execution.isBlank()) {
            requestHeaders.set("X-Logos-Batch-Execution", execution);
        }
        return requestHeaders;
    }

    private ProxiedResponse exchange(HttpMethod method, String path, HttpEntity<?> entity) {
        String url = orchestratorUrl.replaceAll("/+$", "") + path;
        try {
            ResponseEntity<byte[]> response = restTemplate.exchange(url, method, entity, byte[].class);
            if (response.getStatusCode().is3xxRedirection()) {
                // The template never follows a redirect, and the request
                // carries the caller's key — so a 3xx is an error to report,
                // not a hop to take.
                log.warn("batch proxy to {} answered with a redirect: {}", path, response.getStatusCode());
                return new ProxiedResponse(
                    502,
                    MediaType.APPLICATION_JSON_VALUE,
                    "{\"error\":{\"message\":\"The orchestrator answered with a redirect, which the batch proxy does not follow.\"}}"
                        .getBytes(StandardCharsets.UTF_8));
            }
            return new ProxiedResponse(
                response.getStatusCode().value(),
                response.getHeaders().getContentType() != null
                    ? response.getHeaders().getContentType().toString()
                    : MediaType.APPLICATION_JSON_VALUE,
                response.getBody() != null ? response.getBody() : new byte[0]);
        } catch (HttpStatusCodeException exc) {
            // The orchestrator's own error bodies are the useful ones (a line
            // number, a model the key may not use), so they go straight back.
            return new ProxiedResponse(
                exc.getStatusCode().value(),
                MediaType.APPLICATION_JSON_VALUE,
                exc.getResponseBodyAsByteArray());
        } catch (RuntimeException exc) {
            log.warn("batch proxy to {} failed: {}", path, exc.toString());
            return new ProxiedResponse(502, MediaType.APPLICATION_JSON_VALUE,
                "{\"error\":{\"message\":\"The orchestrator is unreachable.\"}}".getBytes(StandardCharsets.UTF_8));
        }
    }

    /** The ``id`` of a JSON object response, without pulling in a parser. */
    private String readId(ProxiedResponse response) {
        String body = new String(response.body(), StandardCharsets.UTF_8);
        int marker = body.indexOf("\"id\"");
        if (marker < 0) {
            return null;
        }
        int open = body.indexOf('"', body.indexOf(':', marker) + 1);
        int close = open < 0 ? -1 : body.indexOf('"', open + 1);
        return (open < 0 || close < 0) ? null : body.substring(open + 1, close);
    }
}
