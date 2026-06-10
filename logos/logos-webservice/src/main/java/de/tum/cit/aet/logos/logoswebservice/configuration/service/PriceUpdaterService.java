package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Async;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelProvider;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Provider;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TokenPrice;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TokenType;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TokenPriceRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TokenTypeRepository;

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

    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;
    private final ModelRepository modelRepository;
    private final ModelProviderRepository modelProviderRepository;
    private final ProviderRepository providerRepository;
    private final TokenTypeRepository tokenTypeRepository;
    private final TokenPriceRepository tokenPriceRepository;

    public PriceUpdaterService(ObjectMapper objectMapper,
                               ModelRepository modelRepository,
                               ModelProviderRepository modelProviderRepository,
                               ProviderRepository providerRepository,
                               TokenTypeRepository tokenTypeRepository,
                               TokenPriceRepository tokenPriceRepository) {
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
        this.modelRepository = modelRepository;
        this.modelProviderRepository = modelProviderRepository;
        this.providerRepository = providerRepository;
        this.tokenTypeRepository = tokenTypeRepository;
        this.tokenPriceRepository = tokenPriceRepository;
    }

    @Scheduled(initialDelay = 0, fixedDelay = 86_400_000)
    public void updateAllModelPrices() {
        log.info("price_updater: starting full refresh");
        List<Provider> cloudProviders = providerRepository.findByCloudProviderTypeIsNotNull();
        if (cloudProviders.isEmpty()) {
            log.info("price_updater: no cloud model-provider pairs, nothing to refresh");
            return;
        }

        int count = 0;
        for (Provider provider : cloudProviders) {
            List<ModelProvider> links = modelProviderRepository.findByProviderId(provider.getId());
            for (ModelProvider link : links) {
                Model model = modelRepository.findById(link.getModelId()).orElse(null);
                if (model == null || model.getName() == null || model.getName().isBlank()) continue;
                try {
                    storePricesForPair(httpClient, model.getId(), model.getName(),
                        provider.getId(), provider.getCloudProviderType().name());
                    count++;
                } catch (Exception e) {
                    log.warn("price_updater: failed for '{}' (id={}): {}", model.getName(), model.getId(), e.getMessage());
                }
            }
        }
        log.info("price_updater: full refresh complete ({} pairs)", count);
    }

    @Async
    public void updatePricesForModelAsync(int modelId, String modelName) {
        try {
            List<ModelProvider> links = modelProviderRepository.findByModelId(modelId);
            List<ModelProvider> cloudLinks = links.stream()
                .filter(link -> providerRepository.findById(link.getProviderId())
                    .map(p -> p.getCloudProviderType() != null)
                    .orElse(false))
                .toList();

            if (cloudLinks.isEmpty()) {
                log.info("price_updater: no cloud providers for '{}' (id={}), skipping", modelName, modelId);
                return;
            }
            for (ModelProvider link : cloudLinks) {
                Provider provider = providerRepository.findById(link.getProviderId()).orElseThrow();
                storePricesForPair(httpClient, modelId, modelName,
                    provider.getId(), provider.getCloudProviderType().name());
            }
        } catch (Exception e) {
            log.warn("price_updater: failed for model '{}' (id={}): {}", modelName, modelId, e.getMessage());
        }
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

    @Transactional
    private void upsertTokenPrice(int modelId, int providerId, String tokenTypeName,
                                  long pricePerK, Instant validFrom) {
        TokenType tokenType = tokenTypeRepository.findByName(tokenTypeName)
            .orElseGet(() -> tokenTypeRepository.save(new TokenType(tokenTypeName)));

        Optional<TokenPrice> latest = tokenPriceRepository
            .findTopByModelIdAndTypeIdAndProviderIdOrderByValidFromDesc(modelId, tokenType.getId(), providerId);

        if (latest.isPresent() && latest.get().getPricePerKToken().longValue() == pricePerK) return;

        Instant from = latest.isEmpty() ? Instant.parse("2020-01-01T00:00:00Z") : validFrom;

        TokenPrice price = new TokenPrice();
        price.setTypeId(tokenType.getId());
        price.setModelId(modelId);
        price.setProviderId(providerId);
        price.setValidFrom(from);
        price.setPricePerKToken(pricePerK);
        tokenPriceRepository.save(price);
    }
}
