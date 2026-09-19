package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * Streams an authenticated request to a cloud upstream (JDK {@link HttpClient}).
 *
 * <p>Connection pool state in the shared {@link HttpClient} is the only process
 * state held here.
 */
@Service
public class GatewayCloudForwarder {

    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;

    public GatewayCloudForwarder(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
    }

    /**
     * Forward to the chosen cloud deployment.
     *
     * @param inferencePath normalized path such as {@code /v1/chat/completions}
     * @param queryString   raw query string without leading {@code ?}, or null
     * @param method        HTTP method
     * @param body          request body bytes (may be empty)
     * @param inboundHeaders inbound request headers to selectively copy (Content-Type)
     * @param onSuccess     invoked after the response body has been fully streamed
     * @param onFailure     invoked when the upstream call or stream fails
     */
    public ResponseEntity<StreamingResponseBody> forward(
            GatewayDeployment deployment,
            String inferencePath,
            String queryString,
            String method,
            byte[] body,
            Map<String, List<String>> inboundHeaders,
            Runnable onSuccess,
            java.util.function.Consumer<String> onFailure) throws IOException {

        String forwardUrl = CloudForwardUrlBuilder.build(
            deployment.baseUrl(), inferencePath, deployment.endpoint());

        Optional<CloudForwardUrlBuilder.AzureResponsesRewrite> responses =
            CloudForwardUrlBuilder.azureResponsesRewrite(forwardUrl);
        String azureDeploymentId = null;
        if (responses.isPresent()) {
            forwardUrl = responses.get().realUrl();
            azureDeploymentId = responses.get().deploymentId();
        }

        forwardUrl = GatewayQueryMerge.merge(forwardUrl, queryString);

        byte[] outboundBody = body;
        if (azureDeploymentId != null && body != null && body.length > 0) {
            outboundBody = rewriteModelField(body, azureDeploymentId);
        }

        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(forwardUrl))
            .timeout(Duration.ofMinutes(10));

        String contentType = firstHeader(inboundHeaders, "content-type");
        if (contentType != null) {
            builder.header("Content-Type", contentType);
        } else if (outboundBody != null && outboundBody.length > 0) {
            builder.header("Content-Type", "application/json");
        }

        CloudAuthHeaders.authHeader(
                deployment.authName(),
                deployment.authFormat(),
                deployment.apiKey(),
                deployment.cloudProviderType())
            .ifPresent(h -> builder.header(h.name(), h.value()));

        for (Map.Entry<String, String> h : CloudAuthHeaders.protocolHeaders(deployment.cloudProviderType()).entrySet()) {
            builder.header(h.getKey(), h.getValue());
        }

        String accept = firstHeader(inboundHeaders, "accept");
        if (accept != null) {
            builder.header("Accept", accept);
        }

        HttpRequest.BodyPublisher publisher = (outboundBody == null || outboundBody.length == 0)
            ? HttpRequest.BodyPublishers.noBody()
            : HttpRequest.BodyPublishers.ofByteArray(outboundBody);
        builder.method(method.toUpperCase(Locale.ROOT), publisher);

        HttpResponse<InputStream> upstream;
        try {
            upstream = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofInputStream());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            if (onFailure != null) {
                onFailure.accept("Interrupted while forwarding to cloud");
            }
            throw new IOException("Interrupted while forwarding to cloud", e);
        } catch (IOException e) {
            if (onFailure != null) {
                onFailure.accept(e.getMessage());
            }
            throw e;
        }

        int status = upstream.statusCode();
        boolean upstreamOk = status >= 200 && status < 400;

        Set<String> exclude = GatewayHopByHop.responseExcludeNames(upstream.headers().map());
        HttpHeaders responseHeaders = new HttpHeaders();
        upstream.headers().map().forEach((name, values) -> {
            if (name == null || exclude.contains(name.toLowerCase(Locale.ROOT))) {
                return;
            }
            responseHeaders.put(name, values);
        });

        InputStream upstreamBody = upstream.body();
        StreamingResponseBody stream = outputStream -> {
            IOException streamError = null;
            try (upstreamBody; OutputStream out = outputStream) {
                upstreamBody.transferTo(out);
                out.flush();
            } catch (IOException e) {
                streamError = e;
            }
            if (streamError != null) {
                if (onFailure != null) {
                    onFailure.accept(streamError.getMessage());
                }
                throw streamError;
            }
            if (upstreamOk) {
                if (onSuccess != null) {
                    onSuccess.run();
                }
            } else if (onFailure != null) {
                onFailure.accept("Upstream HTTP " + status);
            }
        };

        return ResponseEntity.status(status).headers(responseHeaders).body(stream);
    }

    private byte[] rewriteModelField(byte[] body, String deploymentId) throws IOException {
        JsonNode root = objectMapper.readTree(body);
        if (root instanceof ObjectNode obj) {
            obj.put("model", deploymentId);
            return objectMapper.writeValueAsBytes(obj);
        }
        return body;
    }

    private static String firstHeader(Map<String, List<String>> headers, String name) {
        if (headers == null) {
            return null;
        }
        for (Map.Entry<String, List<String>> e : headers.entrySet()) {
            if (e.getKey() != null && e.getKey().equalsIgnoreCase(name)
                && e.getValue() != null && !e.getValue().isEmpty()) {
                return e.getValue().get(0);
            }
        }
        return null;
    }
}
