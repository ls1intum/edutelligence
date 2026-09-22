package de.tum.cit.aet.logos.logoswebservice.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;

/**
 * The direct-cloud path from admission to billed row, against a stand-in cloud
 * upstream.
 *
 * <p>This is the level the flat-rate regression was invisible at: every unit on
 * either side of the forward passed while each request was still billed one
 * cent with no token counts stored. What these cases assert is the end state a
 * request leaves in the database — the cost the budget actually reads.
 */
@SpringBootTest
@Testcontainers
class GatewayCloudBillingEndToEndTest {

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    GatewayCloudAccounting accounting;

    @Autowired
    GatewayCloudForwarder forwarder;

    @MockitoBean
    JwtDecoder jwtDecoder;

    @Container
    @SuppressWarnings("resource")
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:17")
            .withDatabaseName("logosdb")
            .withUsername("postgres")
            .withPassword("root");

    @DynamicPropertySource
    @SuppressWarnings("unused")
    static void configureProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
        registry.add("spring.datasource.driver-class-name", () -> "org.postgresql.Driver");
        registry.add("spring.liquibase.enabled", () -> "true");
        registry.add("spring.liquibase.change-log", () -> "classpath:liquibase/changelog/master.xml");
        registry.add("spring.jpa.hibernate.ddl-auto", () -> "validate");
    }

    private static final AtomicInteger SEQ = new AtomicInteger(1);
    private static final long RESERVATION = 1_000_000L;
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private HttpServer upstream;
    private final AtomicReference<byte[]> seenRequestBody = new AtomicReference<>();

    /** What the stand-in upstream answers with; set per test. */
    private volatile int responseStatus = 200;
    private volatile String responseContentType = "application/json";
    private volatile String responseBody = "{}";

    @BeforeEach
    void startUpstream() throws IOException {
        upstream = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        upstream.createContext("/", exchange -> {
            seenRequestBody.set(exchange.getRequestBody().readAllBytes());
            byte[] out = responseBody.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", responseContentType);
            exchange.sendResponseHeaders(responseStatus, out.length);
            exchange.getResponseBody().write(out);
            exchange.close();
        });
        upstream.start();
    }

    @AfterEach
    void stopUpstream() {
        if (upstream != null) {
            upstream.stop(0);
        }
    }

    // ------------------------------------------------------ non-streaming

    @Test
    void jsonCompletion_isBilledFromItsReportedTokens() throws Exception {
        responseBody = """
            {"id":"chatcmpl-1","choices":[{"message":{"content":"hi"}}],
             "usage":{"prompt_tokens":1000,"completion_tokens":300,"total_tokens":1300}}""";
        Fixture f = seedPricedDeployment();
        int logId = admit(f);

        String delivered = runForward(f, requestBody(false));

        assertThat(delivered).isEqualTo(responseBody);
        assertThat(cost(logId)).isEqualTo(20_000L + 36_000L);
        assertThat(usageTokens(logId)).containsExactlyInAnyOrderEntriesOf(Map.of(
            "prompt_tokens", 1000, "completion_tokens", 300, "total_tokens", 1300));
    }

    @Test
    void jsonCompletion_costReflectsTheActualSizeOfEachRequest() throws Exception {
        // The regression's signature was a constant charge: every call cost the
        // same cent no matter how much it consumed.
        Fixture f = seedPricedDeployment();

        responseBody = "{\"usage\":{\"prompt_tokens\":100,\"completion_tokens\":10}}";
        int smallId = admit(f);
        runForward(f, requestBody(false));

        responseBody = "{\"usage\":{\"prompt_tokens\":100000,\"completion_tokens\":5000}}";
        int largeId = admit(f);
        runForward(f, requestBody(false));

        assertThat(cost(smallId)).isEqualTo(2_000L + 1_200L);
        assertThat(cost(largeId)).isEqualTo(2_000_000L + 600_000L);
        assertThat(cost(largeId)).isGreaterThan(cost(smallId));
        assertThat(List.of(cost(smallId), cost(largeId))).doesNotContain(RESERVATION);
    }

    @Test
    void cachedPromptTokens_reachPricingAsACacheRead() throws Exception {
        Fixture f = seedPricedDeployment();
        seedPrice(f.modelId(), f.providerId(), "billed_input_cache_read", 2000);
        responseBody = """
            {"usage":{"prompt_tokens":1000,"completion_tokens":300,
                      "prompt_tokens_details":{"cached_tokens":800}}}""";
        int logId = admit(f);

        runForward(f, requestBody(false));

        // Losing the cache name would bill all 1000 prompt tokens at the full rate.
        assertThat(cost(logId)).isEqualTo(4_000L + 1_600L + 36_000L);
        assertThat(usageTokens(logId)).containsEntry("prompt_cached_tokens", 800);
    }

    // ---------------------------------------------------------- streaming

    @Test
    void sseStream_isBilledFromTheTerminalUsageChunk() throws Exception {
        responseContentType = "text/event-stream";
        responseBody = """
            data: {"choices":[{"delta":{"content":"hi"}}]}

            data: {"choices":[],"usage":{"prompt_tokens":800,"completion_tokens":200}}

            data: [DONE]

            """;
        Fixture f = seedPricedDeployment();
        int logId = admit(f);

        String delivered = runForward(f, requestBody(true));

        assertThat(delivered).isEqualTo(responseBody);
        assertThat(cost(logId)).isEqualTo(16_000L + 24_000L);
        assertThat(usageTokens(logId)).containsExactlyInAnyOrderEntriesOf(Map.of(
            "prompt_tokens", 800, "completion_tokens", 200));
    }

    @Test
    void streamingRequest_asksTheUpstreamToReportUsage() throws Exception {
        // Without this the stream ends with no counts at all and the request
        // cannot be priced.
        responseContentType = "text/event-stream";
        responseBody = "data: [DONE]\n\n";
        Fixture f = seedPricedDeployment();
        admit(f);

        runForward(f, requestBody(true));

        JsonNode sent = MAPPER.readTree(seenRequestBody.get());
        assertThat(sent.path("stream_options").path("include_usage").asBoolean()).isTrue();
        assertThat(sent.path("model").asText()).isEqualTo("m");
    }

    @Test
    void nonStreamingRequest_isForwardedUnchanged() throws Exception {
        responseBody = "{\"usage\":{\"prompt_tokens\":5}}";
        Fixture f = seedPricedDeployment();
        admit(f);

        byte[] original = requestBody(false);
        runForward(f, original);

        assertThat(MAPPER.readTree(seenRequestBody.get()).has("stream_options")).isFalse();
        assertThat(MAPPER.readTree(seenRequestBody.get())).isEqualTo(MAPPER.readTree(original));
    }

    @Test
    void responsesSurface_doesNotGetStreamOptions() throws Exception {
        // The Responses API rejects stream_options as unknown; it reports usage
        // on its terminal event instead.
        responseContentType = "text/event-stream";
        responseBody = """
            data: {"type":"response.completed","response":{"usage":{"input_tokens":64,"output_tokens":12}}}

            """;
        Fixture f = seedPricedDeployment();
        int logId = admit(f);

        runForward(f, requestBody(true), "/v1/responses");

        assertThat(MAPPER.readTree(seenRequestBody.get()).has("stream_options")).isFalse();
        assertThat(cost(logId)).isEqualTo(64L * 20_000 / 1000 + 12L * 120_000 / 1000);
    }

    @Test
    void imageAndAudioSurfaces_doNotGetStreamOptions() throws Exception {
        // stream_options belongs to Chat Completions; other direct-cloud
        // surfaces may reject it as unknown.
        responseBody = "{\"data\":[]}";
        Fixture f = seedPricedDeployment();
        admit(f, requestBody(true));

        runForward(f, requestBody(true), "/v1/images/generations");

        assertThat(MAPPER.readTree(seenRequestBody.get()).has("stream_options")).isFalse();
    }

    @Test
    void surfaceCompatibilityIsDecidedPositively() {
        assertThat(GatewayCloudForwarder.acceptsStreamOptions(
            "https://x/v1/chat/completions")).isTrue();
        assertThat(GatewayCloudForwarder.acceptsStreamOptions(
            "https://x/openai/deployments/d/chat/completions?api-version=2025-01-01")).isTrue();
        assertThat(GatewayCloudForwarder.acceptsStreamOptions("https://x/v1/responses")).isFalse();
        assertThat(GatewayCloudForwarder.acceptsStreamOptions("https://x/v1/embeddings")).isFalse();
        assertThat(GatewayCloudForwarder.acceptsStreamOptions("https://x/v1/images/generations")).isFalse();
        assertThat(GatewayCloudForwarder.acceptsStreamOptions("https://x/v1/audio/speech")).isFalse();
    }

    @Test
    void deploymentWithoutPrices_keepsTheReservationRatherThanBillingNothing() throws Exception {
        responseBody = "{\"usage\":{\"prompt_tokens\":1000,\"completion_tokens\":300}}";
        Fixture f = seedUnpricedDeployment();
        int logId = admit(f);

        runForward(f, requestBody(false));

        assertThat(cost(logId)).isEqualTo(RESERVATION);
        assertThat(usageTokens(logId)).containsEntry("prompt_tokens", 1000);
    }

    // ------------------------------------------------------- fallback paths

    @Test
    void streamWithoutUsage_keepsTheReservationRatherThanBillingNothing() throws Exception {
        responseContentType = "text/event-stream";
        responseBody = """
            data: {"choices":[{"delta":{"content":"hi"}}]}

            data: [DONE]

            """;
        Fixture f = seedPricedDeployment();
        int logId = admit(f);

        runForward(f, requestBody(true));

        assertThat(cost(logId)).isEqualTo(RESERVATION);
        assertThat(usageTokens(logId)).isEmpty();
        assertThat(status(logId)).isEqualTo("success");
    }

    @Test
    void upstreamError_isNotBilled() throws Exception {
        responseStatus = 500;
        responseBody = "{\"error\":{\"message\":\"upstream exploded\"}}";
        Fixture f = seedPricedDeployment();
        int logId = admit(f);

        runForward(f, requestBody(false));

        assertThat(cost(logId)).isZero();
        assertThat(status(logId)).isEqualTo("error");
        assertThat(usageTokens(logId)).isEmpty();
    }

    @Test
    void clientDisconnectMidStream_isNotBilled() throws Exception {
        responseContentType = "text/event-stream";
        responseBody = "data: {\"usage\":{\"prompt_tokens\":10}}\n\n";
        Fixture f = seedPricedDeployment();
        int logId = admit(f);

        ResponseEntity<StreamingResponseBody> response = forward(f, requestBody(true), "/v1/chat/completions");
        assertThatThrownBy(() -> response.getBody().writeTo(new OutputStream() {
            @Override
            public void write(int b) throws IOException {
                throw new IOException("client went away");
            }

            @Override
            public void write(byte[] b, int off, int len) throws IOException {
                throw new IOException("client went away");
            }
        })).isInstanceOf(IOException.class);

        assertThat(cost(logId)).isZero();
        assertThat(status(logId)).isEqualTo("error");
    }

    // ------------------------------------------------------- payload logging

    @Test
    void fullLoggingKey_storesBothPayloadsAtItsOwnLevel() throws Exception {
        // The key's configured level decides this, not the gateway: a key set to
        // FULL is logged with its payloads exactly as on the orchestrator path.
        responseBody = "{\"id\":\"chatcmpl-1\",\"usage\":{\"prompt_tokens\":10,\"completion_tokens\":2}}";
        Fixture f = seedPricedDeployment("FULL");
        int logId = admit(f);

        runForward(f, requestBody(false));

        assertThat(privacyLevel(logId)).isEqualTo("FULL");
        assertThat(MAPPER.readTree(inputPayload(logId)).path("model").asText()).isEqualTo("m");
        assertThat(MAPPER.readTree(responsePayload(logId)).path("usage").path("prompt_tokens").asInt())
            .isEqualTo(10);
    }

    @Test
    void billingLevelKey_storesNoPayloads() throws Exception {
        responseBody = "{\"usage\":{\"prompt_tokens\":10}}";
        Fixture f = seedPricedDeployment("BILLING");
        int logId = admit(f);

        runForward(f, requestBody(false));

        assertThat(privacyLevel(logId)).isEqualTo("BILLING");
        assertThat(inputPayload(logId)).isNull();
        assertThat(responsePayload(logId)).isNull();
    }

    @Test
    void fullLoggingKey_streamHasNoSingleResponseBodyToStore() throws Exception {
        // A stream is still logged at its level with its request payload; only
        // the response body has no one document to store.
        responseContentType = "text/event-stream";
        responseBody = "data: {\"usage\":{\"prompt_tokens\":9}}\n\ndata: [DONE]\n\n";
        Fixture f = seedPricedDeployment("FULL");
        int logId = admit(f, requestBody(true));

        runForward(f, requestBody(true));

        assertThat(privacyLevel(logId)).isEqualTo("FULL");
        assertThat(MAPPER.readTree(inputPayload(logId)).path("stream").asBoolean()).isTrue();
        assertThat(responsePayload(logId)).isNull();
        // Billing is unaffected either way.
        assertThat(usageTokens(logId)).containsEntry("prompt_tokens", 9);
    }

    @Test
    void fullLoggingKey_nonJsonResponseIsNotStoredAndDoesNotFailTheRequest() throws Exception {
        responseContentType = "text/plain";
        responseBody = "not json at all";
        Fixture f = seedPricedDeployment("FULL");
        int logId = admit(f);

        String delivered = runForward(f, requestBody(false));

        assertThat(delivered).isEqualTo(responseBody);
        assertThat(responsePayload(logId)).isNull();
        assertThat(status(logId)).isEqualTo("success");
    }

    // --------------------------------------------------------------- helpers

    private record Fixture(int modelId, int providerId, GatewayKey key, GatewayDeployment deployment) {
    }

    private byte[] requestBody(boolean stream) {
        return ("{\"model\":\"m\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]"
            + (stream ? ",\"stream\":true" : "") + "}").getBytes(StandardCharsets.UTF_8);
    }

    private int admit(Fixture f) {
        return admit(f, requestBody(false));
    }

    private int admit(Fixture f, byte[] body) {
        Integer id = accounting.admitAndReserve(f.key(), f.deployment(), null, body);
        assertThat(id).isNotNull();
        assertThat(settledCost(id)).isEqualTo(RESERVATION);
        return id;
    }

    private String runForward(Fixture f, byte[] body) throws IOException {
        return runForward(f, body, "/v1/chat/completions");
    }

    /** Forward and drain the response the way the servlet container would. */
    private String runForward(Fixture f, byte[] body, String path) throws IOException {
        ResponseEntity<StreamingResponseBody> response = forward(f, body, path);
        ByteArrayOutputStream client = new ByteArrayOutputStream();
        response.getBody().writeTo(client);
        return client.toString(StandardCharsets.UTF_8);
    }

    private ResponseEntity<StreamingResponseBody> forward(Fixture f, byte[] body, String path) throws IOException {
        Integer logId = latestLogId(f);
        return forwarder.forward(
            f.deployment(), path, null, "POST", body,
            Map.of("content-type", List.of("application/json")),
            f.key().logsFullPayloads(),
            result -> accounting.settleSuccess(logId, result.usage(), result.responseBody()),
            err -> accounting.settleFailure(logId, err));
    }

    /** The reservation this forward belongs to — the one the controller just made. */
    private Integer latestLogId(Fixture f) {
        return jdbc.queryForObject(
            "SELECT id FROM log_entry WHERE api_key_id = ? ORDER BY id DESC LIMIT 1",
            Integer.class, f.key().id());
    }

    private Fixture seedPricedDeployment() {
        return seedPricedDeployment("BILLING");
    }

    /** Same shape, but no price rows — the deployment nothing can be charged for. */
    private Fixture seedUnpricedDeployment() {
        return seedDeployment("BILLING", false);
    }

    private Fixture seedPricedDeployment(String logLevel) {
        return seedDeployment(logLevel, true);
    }

    private Fixture seedDeployment(String logLevel, boolean priced) {
        int modelId = jdbc.queryForObject(
            "INSERT INTO models (name) VALUES (?) RETURNING id",
            Integer.class, "m-" + SEQ.getAndIncrement());
        int providerId = jdbc.queryForObject(
            "INSERT INTO providers (name, base_url, provider_type, cloud_provider_type, auth_name, auth_format) "
            + "VALUES (?, ?, 'cloud', 'openai'::cloud_provider_type_enum, 'Authorization', 'Bearer %s') "
            + "RETURNING id",
            Integer.class, "p-" + SEQ.getAndIncrement(), upstreamBaseUrl());
        if (priced) {
            seedPrice(modelId, providerId, "billed_input_uncached", 20000);
            seedPrice(modelId, providerId, "billed_output_text", 120000);
        }

        int teamId = jdbc.queryForObject(
            "INSERT INTO teams (name) VALUES (?) RETURNING id",
            Integer.class, "t-" + SEQ.getAndIncrement());
        int apiKeyId = jdbc.queryForObject(
            "INSERT INTO api_keys (key_value, name, team_id, log) "
            + "VALUES (?, ?, ?, ?::logging_enum) RETURNING id",
            Integer.class, "lg-" + SEQ.getAndIncrement(), "k-" + SEQ.get(), teamId, logLevel);

        GatewayKey key = new GatewayKey(apiKeyId, "lg-x", "k", ApiKeyType.developer,
            teamId, null, "test", false, null, 0, logLevel);
        GatewayDeployment deployment = new GatewayDeployment(modelId, "m", providerId, "p",
            "cloud", "openai", upstreamBaseUrl(), null,
            "Authorization", "Bearer %s", "sk-x", "BILLING", null);
        return new Fixture(modelId, providerId, key, deployment);
    }

    private String upstreamBaseUrl() {
        return "http://127.0.0.1:" + upstream.getAddress().getPort();
    }

    private void seedPrice(int modelId, int providerId, String typeName, long pricePerKUnit) {
        jdbc.update("INSERT INTO token_types (name) VALUES (?) ON CONFLICT (name) DO NOTHING", typeName);
        jdbc.update(
            "INSERT INTO token_prices (type_id, model_id, provider_id, unit, min_context_tokens, "
            + "service_tier, valid_from, price_per_k_unit) VALUES "
            + "((SELECT id FROM token_types WHERE name = ?), ?, ?, 'token', 0, 'default', "
            + "'2020-01-01T00:00:00Z'::timestamptz, ?)",
            typeName, modelId, providerId, pricePerKUnit);
    }

    private Long cost(int logEntryId) {
        return jdbc.queryForObject(
            "SELECT cost_micro_cents FROM log_entry_cost WHERE log_entry_id = ?", Long.class, logEntryId);
    }

    private Long settledCost(int logEntryId) {
        return jdbc.queryForObject(
            "SELECT settled_cost_micro_cents FROM log_entry WHERE id = ?", Long.class, logEntryId);
    }

    private String status(int logEntryId) {
        return jdbc.queryForObject(
            "SELECT result_status::text FROM log_entry WHERE id = ?", String.class, logEntryId);
    }

    private String privacyLevel(int logEntryId) {
        return jdbc.queryForObject(
            "SELECT privacy_level::text FROM log_entry WHERE id = ?", String.class, logEntryId);
    }

    private String inputPayload(int logEntryId) {
        return jdbc.queryForObject(
            "SELECT input_payload::text FROM log_entry WHERE id = ?", String.class, logEntryId);
    }

    private String responsePayload(int logEntryId) {
        return jdbc.queryForObject(
            "SELECT response_payload::text FROM log_entry WHERE id = ?", String.class, logEntryId);
    }

    private Map<String, Integer> usageTokens(int logEntryId) {
        Map<String, Integer> out = new java.util.LinkedHashMap<>();
        jdbc.query("SELECT tt.name, ut.token_count FROM usage_tokens ut "
            + "JOIN token_types tt ON tt.id = ut.type_id WHERE ut.log_entry_id = ?",
            rs -> {
                out.put(rs.getString(1), rs.getInt(2));
            }, logEntryId);
        return out;
    }
}
