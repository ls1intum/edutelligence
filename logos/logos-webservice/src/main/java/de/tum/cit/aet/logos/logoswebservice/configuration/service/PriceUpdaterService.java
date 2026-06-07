package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.ObjectMapper;

@Service
public class PriceUpdaterService {

    private static final Logger log = LoggerFactory.getLogger(PriceUpdaterService.class);
    private static final String LITELLM_BASE = "https://api.litellm.ai/model_catalog";

    private static final Map<String, String> LITELLM_TO_TOKEN_TYPE = Map.of(
        "input_cost_per_token", "prompt_tokens",
        "output_cost_per_token", "completion_tokens",
        "cache_read_input_token_cost", "prompt_cached_tokens",
        "output_cost_per_reasoning_token", "completion_reasoning_tokens",
        "input_cost_per_audio_token", "prompt_audio_tokens",
        "output_cost_per_audio_token", "completion_audio_tokens"
    );

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public PriceUpdaterService(JdbcTemplate jdbc, ObjectMapper objectMapper) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
    }

    @Scheduled(initialDelay = 0, fixedDelay = 86_400_000)
    public void updateAllModelPrices() {
        log.info("price_updater: starting full refresh");
        List<Map<String, Object>> pairs = jdbc.queryForList("""
            SELECT m.id AS model_id, m.name AS model_name,
                   p.id AS provider_id, p.cloud_provider_type
            FROM models m
            JOIN model_provider mp ON mp.model_id = m.id
            JOIN providers p ON p.id = mp.provider_id
            WHERE p.cloud_provider_type IS NOT NULL
            ORDER BY m.id, p.id
            """);

        if (pairs.isEmpty()) {
            log.info("price_updater: no cloud model-provider pairs, nothing to refresh");
            return;
        }

        for (Map<String, Object> pair : pairs) {
            int modelId = ((Number) pair.get("model_id")).intValue();
            String name = (String) pair.get("model_name");
            int providerId = ((Number) pair.get("provider_id")).intValue();
            String ct = (String) pair.get("cloud_provider_type");
            if (name == null || name.isBlank()) continue;
            try {
                storePricesForPair(httpClient, modelId, name, providerId, ct);
            } catch (Exception e) {
                log.warn("price_updater: failed for '{}' (id={}): {}", name, modelId, e.getMessage());
            }
        }
        log.info("price_updater: full refresh complete ({} pairs)", pairs.size());
    }

    public void updatePricesForModelAsync(int modelId, String modelName) {
        Thread.ofVirtual().start(() -> {
            try {
                List<Map<String, Object>> providers = jdbc.queryForList("""
                    SELECT p.id AS provider_id, p.cloud_provider_type
                    FROM model_provider mp
                    JOIN providers p ON p.id = mp.provider_id
                    WHERE mp.model_id = ? AND p.cloud_provider_type IS NOT NULL
                    """, modelId);
                if (providers.isEmpty()) {
                    log.info("price_updater: no cloud providers for '{}' (id={}), skipping", modelName, modelId);
                    return;
                }
                for (Map<String, Object> p : providers) {
                    storePricesForPair(httpClient,
                        modelId, modelName,
                        ((Number) p.get("provider_id")).intValue(),
                        (String) p.get("cloud_provider_type"));
                }
            } catch (Exception e) {
                log.warn("price_updater: failed for model '{}' (id={}): {}", modelName, modelId, e.getMessage());
            }
        });
    }

    private void storePricesForPair(HttpClient client,
                                    int modelId, String modelName,
                                    int providerId, String cloudType) {
        String candidate = (cloudType == null || "openai".equals(cloudType))
            ? modelName : cloudType + "/" + modelName;

        Map<String, Object> data = fetchModelData(client, candidate);
        if (data == null && !candidate.equals(modelName)) {
            data = fetchModelData(client, modelName);
        }
        if (data == null) {
            log.info("price_updater: '{}' (provider_id={}) not found in litellm catalog, will be free",
                modelName, providerId);
            return;
        }

        Instant validFrom = Instant.now();
        for (Map.Entry<String, String> entry : LITELLM_TO_TOKEN_TYPE.entrySet()) {
            Object costObj = data.get(entry.getKey());
            if (costObj == null) continue;
            double cost = ((Number) costObj).doubleValue();
            if (cost <= 0) continue;
            long pricePerK = Math.round(cost * 1e11);
            upsertTokenPrice(modelId, providerId, entry.getValue(), pricePerK, validFrom);
        }
        log.info("price_updater: prices updated for '{}' (id={}, provider_id={})", modelName, modelId, providerId);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> fetchModelData(HttpClient client, String modelName) {
        for (String candidate : List.of(modelName, modelName.toLowerCase())) {
            try {
                HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(LITELLM_BASE + "/" + candidate))
                    .timeout(Duration.ofSeconds(30))
                    .GET()
                    .build();
                HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());
                if (resp.statusCode() == 200) {
                    return objectMapper.readValue(resp.body(), Map.class);
                }
            } catch (Exception e) {
                log.warn("price_updater: HTTP error for '{}': {}", candidate, e.getMessage());
                return null;
            }
        }
        return null;
    }

    private void upsertTokenPrice(int modelId, int providerId, String tokenTypeName,
                                  long pricePerK, Instant validFrom) {
        jdbc.update("""
            INSERT INTO token_types (name) VALUES (?)
            ON CONFLICT (name) DO NOTHING
            """, tokenTypeName);

        Integer typeId = jdbc.queryForObject(
            "SELECT id FROM token_types WHERE name = ?", Integer.class, tokenTypeName);
        if (typeId == null) return;

        List<Long> existing = jdbc.queryForList("""
            SELECT price_per_k_token FROM token_prices
            WHERE model_id = ? AND type_id = ? AND provider_id = ?
            ORDER BY valid_from DESC LIMIT 1
            """, Long.class, modelId, typeId, providerId);

        if (!existing.isEmpty() && existing.get(0) == pricePerK) return;

        Instant from = existing.isEmpty()
            ? Instant.parse("2020-01-01T00:00:00Z")
            : validFrom;

        jdbc.update("""
            INSERT INTO token_prices (type_id, model_id, provider_id, valid_from, price_per_k_token)
            VALUES (?, ?, ?, ?, ?)
            """, typeId, modelId, providerId, Timestamp.from(from), pricePerK);
    }
}
