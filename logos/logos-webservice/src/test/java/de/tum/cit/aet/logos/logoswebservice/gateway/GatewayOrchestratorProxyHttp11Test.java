package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import com.sun.net.httpserver.Headers;
import com.sun.net.httpserver.HttpServer;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

/**
 * Regression for the prod failure where the JDK {@code HttpClient}'s default
 * {@code Upgrade: h2c} preface left uvicorn reading an empty body
 * ({@code 400 Invalid JSON body}) on proxied {@code /v1/messages} POSTs.
 */
class GatewayOrchestratorProxyHttp11Test {

    private HttpServer server;
    private final AtomicReference<byte[]> seenBody = new AtomicReference<>();
    private final AtomicReference<Headers> seenHeaders = new AtomicReference<>();

    @BeforeEach
    void startServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/messages", exchange -> {
            seenHeaders.set(exchange.getRequestHeaders());
            seenBody.set(exchange.getRequestBody().readAllBytes());
            byte[] ok = "{\"ok\":true}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, ok.length);
            exchange.getResponseBody().write(ok);
            exchange.close();
        });
        server.start();
    }

    @AfterEach
    void stopServer() {
        if (server != null) {
            server.stop(0);
        }
    }

    @Test
    void proxyPostsJsonBodyOverPlainHttp11WithoutH2cUpgrade() throws Exception {
        String base = "http://127.0.0.1:" + server.getAddress().getPort();
        GatewayOrchestratorProxy proxy = new GatewayOrchestratorProxy(base);

        byte[] body = """
            {"model":"claude-opus-5","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}
            """.strip().getBytes(StandardCharsets.UTF_8);

        MockHttpServletRequest inbound = new MockHttpServletRequest("POST", "/v1/messages");
        inbound.setQueryString("beta=true");
        inbound.addHeader("Authorization", "Bearer lg-test-key");
        inbound.addHeader("Content-Type", "application/json");
        inbound.addHeader("anthropic-version", "2023-06-01");

        ResponseEntity<StreamingResponseBody> response = proxy.proxy(inbound, "/v1/messages", body);
        assertThat(response.getStatusCode().value()).isEqualTo(200);

        ByteArrayOutputStream drained = new ByteArrayOutputStream();
        response.getBody().writeTo(drained);
        assertThat(drained.toString(StandardCharsets.UTF_8)).contains("\"ok\":true");

        assertThat(seenBody.get()).isEqualTo(body);

        Headers headers = seenHeaders.get();
        assertThat(headers.getFirst("Authorization")).isEqualTo("Bearer lg-test-key");
        assertThat(headers.getFirst("Content-Type")).isEqualTo("application/json");
        // Default JDK HttpClient would send these and break uvicorn body reads.
        assertThat(headerNames(headers)).noneMatch(n -> n.equalsIgnoreCase("Upgrade"));
        assertThat(headerNames(headers)).noneMatch(n -> n.equalsIgnoreCase("HTTP2-Settings"));
        List<String> connection = headers.get("Connection");
        if (connection != null) {
            assertThat(String.join(",", connection).toLowerCase()).doesNotContain("upgrade");
            assertThat(String.join(",", connection).toLowerCase()).doesNotContain("http2-settings");
        }
    }

    private static List<String> headerNames(Headers headers) {
        return headers.keySet().stream().toList();
    }
}
