package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestTemplate;

import de.tum.cit.aet.logos.logoswebservice.common.RestTemplateConfig;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * The batch proxy authenticates with a scoped credential, not the user's
 * key value: the key is a long-lived secret, and the shipped setup reaches
 * the orchestrator over plain HTTP. These tests pin down what may travel —
 * and what keeps the raw key out of every request.
 */
class BatchServiceTest {

    private static final String RAW_KEY = "lg-raw-secret-value";
    private static final String CREDENTIAL = "bc1.test-credential";

    private HttpServer server;
    private final Map<String, String> seenHeaders = new ConcurrentHashMap<>();
    private final Map<String, String> seenBodies = new ConcurrentHashMap<>();

    @BeforeEach
    void startServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/batch_credentials", exchange -> {
            seenHeaders.put("internal-authorization", exchange.getRequestHeaders().getFirst("Authorization"));
            seenBodies.put("internal", new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] body = ("{\"credential\":\"" + CREDENTIAL + "\",\"expires_in\":300}").getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.createContext("/v1/batches", exchange -> {
            // Longer than the old 5 s read timeout: a legitimate slow
            // orchestrator answer (the upload there covers validation, a cold
            // capability probe, and the provider upload) must not 502.
            try {
                Thread.sleep(6_000);
            } catch (InterruptedException exc) {
                Thread.currentThread().interrupt();
            }
            seenHeaders.put("batches-logos-key", exchange.getRequestHeaders().getFirst("logos_key"));
            byte[] body = "{\"data\":[]}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }

    private ApiKey keyOwnedBy(int userId, int keyId) {
        ApiKey key = mock(ApiKey.class);
        when(key.getId()).thenReturn(keyId);
        when(key.getKeyValue()).thenReturn(RAW_KEY);
        when(key.getIsActive()).thenReturn(true);
        when(key.getUserId()).thenReturn(userId);
        return key;
    }

    private BatchService service(RestTemplate restTemplate, ApiKeyRepository repository,
                                 String orchestratorUrl, String internalSecret) {
        BatchService service = new BatchService(restTemplate, repository);
        ReflectionTestUtils.setField(service, "orchestratorUrl", orchestratorUrl);
        ReflectionTestUtils.setField(service, "internalSecret", internalSecret);
        return service;
    }

    @Test
    void the_raw_key_never_leaves_the_process_and_a_slow_answer_is_not_cut_off() {
        ApiKeyRepository repository = mock(ApiKeyRepository.class);
        ApiKey key = keyOwnedBy(1, 5);
        when(repository.findById(5)).thenReturn(Optional.of(key));
        BatchService service = service(new RestTemplateConfig().batchRestTemplate(), repository,
            "http://127.0.0.1:" + server.getAddress().getPort(), "internal");

        BatchService.ProxiedResponse response = service.listBatches(1, 5);

        assertThat(response.status()).isEqualTo(200);
        // The Batch API call carries the exchanged credential — and only it.
        assertThat(seenHeaders.get("batches-logos-key")).isEqualTo(CREDENTIAL);
        // The exchange itself is secret-gated and names the key by id.
        assertThat(seenHeaders.get("internal-authorization")).isEqualTo("Bearer internal");
        assertThat(seenBodies.get("internal")).contains("\"api_key_id\":5");
        // The raw key value is in neither request.
        assertThat(seenHeaders.values()).doesNotContain(RAW_KEY);
        assertThat(seenBodies.values()).noneSatisfy(body -> assertThat(body).contains(RAW_KEY));
    }

    @Test
    void a_slow_upload_does_not_carry_its_aged_credential_into_the_creation() throws IOException {
        // The upload may itself take most of the credential's life; the
        // creation that follows it must present a fresh exchange, not the one
        // the upload already aged out — or it 401s after the file was stored,
        // leaving the file behind with no batch to spend it on.
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicInteger exchanges = new AtomicInteger();
        Map<String, String> keys = new ConcurrentHashMap<>();
        server.createContext("/internal/batch_credentials", exchange -> {
            String credential = exchanges.getAndIncrement() == 0 ? "bc1.aged" : "bc1.fresh";
            byte[] body = ("{\"credential\":\"" + credential + "\",\"expires_in\":300}").getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.createContext("/v1/files", exchange -> {
            keys.put("files-logos-key", exchange.getRequestHeaders().getFirst("logos_key"));
            byte[] body = "{\"id\":\"file-1\"}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.createContext("/v1/batches", exchange -> {
            keys.put("batches-logos-key", exchange.getRequestHeaders().getFirst("logos_key"));
            // The credential the upload used is expired by the time the creation goes out.
            if ("bc1.aged".equals(exchange.getRequestHeaders().getFirst("logos_key"))) {
                byte[] body = "{\"error\":{\"message\":\"the credential is no longer valid\"}}"
                    .getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().add("Content-Type", "application/json");
                exchange.sendResponseHeaders(401, body.length);
                exchange.getResponseBody().write(body);
                exchange.close();
                return;
            }
            byte[] body = "{\"id\":\"batch_1\"}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        try {
            ApiKeyRepository repository = mock(ApiKeyRepository.class);
            ApiKey key = keyOwnedBy(1, 5);
            when(repository.findById(5)).thenReturn(Optional.of(key));
            BatchService service = service(new RestTemplateConfig().batchRestTemplate(), repository,
                "http://127.0.0.1:" + server.getAddress().getPort(), "internal");

            BatchService.ProxiedResponse response = service.createBatch(1, 5, "batch.jsonl",
                "{\"custom_id\":\"one\"}".getBytes(StandardCharsets.UTF_8), "/v1/chat/completions", "24h", "auto");

            assertThat(response.status()).isEqualTo(200);
            // The upload carried the first exchange; the creation the fresh one.
            assertThat(keys.get("files-logos-key")).isEqualTo("bc1.aged");
            assertThat(keys.get("batches-logos-key")).isEqualTo("bc1.fresh");
            assertThat(exchanges.get()).isEqualTo(2);
        } finally {
            server.stop(0);
        }
    }

    @Test
    void a_key_the_caller_does_not_own_is_rejected_before_any_orchestrator_call() {
        RestTemplate restTemplate = mock(RestTemplate.class);
        ApiKeyRepository repository = mock(ApiKeyRepository.class);
        ApiKey otherUsersKey = keyOwnedBy(2, 5);  // another user's key
        when(repository.findById(5)).thenReturn(Optional.of(otherUsersKey));
        BatchService service = service(restTemplate, repository, "http://127.0.0.1:1", "internal");

        assertThatThrownBy(() -> service.listBatches(1, 5))
            .isInstanceOf(BatchService.KeyNotOwnedException.class);
        verifyNoInteractions(restTemplate);
    }

    @Test
    void a_refused_exchange_is_an_exchange_error_not_a_proxied_answer() {
        RestTemplate restTemplate = mock(RestTemplate.class);
        when(restTemplate.exchange(anyString(), eq(HttpMethod.POST), any(HttpEntity.class), eq(byte[].class)))
            .thenReturn(ResponseEntity.status(HttpStatus.NOT_FOUND).body(new byte[0]));
        ApiKeyRepository repository = mock(ApiKeyRepository.class);
        ApiKey key = keyOwnedBy(1, 5);
        when(repository.findById(5)).thenReturn(Optional.of(key));
        BatchService service = service(restTemplate, repository, "http://127.0.0.1:1", "internal");

        assertThatThrownBy(() -> service.listBatches(1, 5))
            .isInstanceOf(BatchService.CredentialExchangeException.class);
    }

    @Test
    void a_missing_internal_secret_is_an_exchange_error() {
        RestTemplate restTemplate = mock(RestTemplate.class);
        ApiKeyRepository repository = mock(ApiKeyRepository.class);
        ApiKey key = keyOwnedBy(1, 5);
        when(repository.findById(5)).thenReturn(Optional.of(key));
        BatchService service = service(restTemplate, repository, "http://127.0.0.1:1", "");

        assertThatThrownBy(() -> service.listBatches(1, 5))
            .isInstanceOf(BatchService.CredentialExchangeException.class);
        verifyNoInteractions(restTemplate);
    }

    @Test
    void the_startup_validation_permits_the_internal_service_url_when_the_exchange_is_configured() {
        // The value the shipped Compose files configure: plain HTTP, and not
        // loopback. With the exchange configured, that is exactly what the
        // URL is permitted for.
        BatchService service = service(mock(RestTemplate.class), mock(ApiKeyRepository.class),
            "http://logos-orchestrator:8080", "some-secret");

        assertThatCode(service::validateOrchestratorUrl).doesNotThrowAnyException();
    }

    @Test
    void the_startup_validation_still_refuses_a_cleartext_url_without_the_exchange() {
        BatchService service = service(mock(RestTemplate.class), mock(ApiKeyRepository.class),
            "http://logos-orchestrator:8080", "");

        assertThatThrownBy(service::validateOrchestratorUrl).isInstanceOf(IllegalStateException.class);
    }

    @Test
    void loopback_and_https_need_no_exchange_to_be_permitted() {
        BatchService loopback = service(mock(RestTemplate.class), mock(ApiKeyRepository.class),
            "http://localhost:8080", "");
        assertThatCode(loopback::validateOrchestratorUrl).doesNotThrowAnyException();

        BatchService https = service(mock(RestTemplate.class), mock(ApiKeyRepository.class),
            "https://orchestrator.example.com", "");
        assertThatCode(https::validateOrchestratorUrl).doesNotThrowAnyException();
    }
}
