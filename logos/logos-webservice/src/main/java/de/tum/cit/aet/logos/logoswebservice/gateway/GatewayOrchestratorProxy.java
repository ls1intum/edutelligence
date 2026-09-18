package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Enumeration;
import java.util.Locale;
import java.util.Set;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import jakarta.servlet.http.HttpServletRequest;

/**
 * Reverse-proxies inference traffic to {@code logos.orchestrator.url},
 * preserving method, path, query, body, and streaming, and passing through
 * the caller's Logos API key headers.
 *
 * <p>Connection pool state in the shared {@link HttpClient} is the only
 * process state held here.
 */
@Service
public class GatewayOrchestratorProxy {

    private final HttpClient httpClient;
    private final String orchestratorUrl;

    public GatewayOrchestratorProxy(@Value("${logos.orchestrator.url:}") String orchestratorUrl) {
        this.orchestratorUrl = orchestratorUrl == null ? "" : orchestratorUrl.strip().replaceAll("/+$", "");
        this.httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();
    }

    /**
     * Proxy the inbound request to the orchestrator.
     *
     * @param pathWithinApp path within the app including leading slash
     * @param body          already-buffered body (may be empty); used so the
     *                      controller can peek at {@code model} before proxying
     */
    public ResponseEntity<StreamingResponseBody> proxy(
            HttpServletRequest request,
            String pathWithinApp,
            byte[] body) throws IOException {
        if (orchestratorUrl.isBlank()) {
            throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE, "logos.orchestrator.url is not configured");
        }

        String query = request.getQueryString();
        String target = orchestratorUrl + pathWithinApp
            + (query == null || query.isBlank() ? "" : "?" + query);

        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(target))
            .timeout(Duration.ofMinutes(30));

        Enumeration<String> headerNames = request.getHeaderNames();
        while (headerNames != null && headerNames.hasMoreElements()) {
            String name = headerNames.nextElement();
            if (name == null || GatewayHopByHop.isRequestHopByHop(name)) {
                continue;
            }
            Enumeration<String> values = request.getHeaders(name);
            while (values.hasMoreElements()) {
                builder.header(name, values.nextElement());
            }
        }

        byte[] outbound = body == null ? new byte[0] : body;
        HttpRequest.BodyPublisher publisher = outbound.length == 0
            ? HttpRequest.BodyPublishers.noBody()
            : HttpRequest.BodyPublishers.ofByteArray(outbound);
        builder.method(request.getMethod().toUpperCase(Locale.ROOT), publisher);

        HttpResponse<InputStream> upstream;
        try {
            upstream = httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofInputStream());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("Interrupted while proxying to orchestrator", e);
        }

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
            try (upstreamBody; OutputStream out = outputStream) {
                upstreamBody.transferTo(out);
                out.flush();
            }
        };

        return ResponseEntity.status(upstream.statusCode()).headers(responseHeaders).body(stream);
    }
}
