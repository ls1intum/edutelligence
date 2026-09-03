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
import java.util.regex.Matcher;
import java.util.regex.Pattern;

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

    /** A litellm per-unit price maps to one billable-quantity type and its unit. */
    private record TypeUnit(String quantity, String unit) {}

    /**
     * EXTENSION POINT: to bill a new cost dimension, add a
     * {@code (litellm catalog key) -> (billable quantity name, unit)} entry here
     * plus the matching {@code token_types} row in changelog 022. An unmapped key
     * is ignored (that dimension stays unpriced), never a crash.
     */
    private static final Map<String, TypeUnit> LITELLM_BASE_KEYS = Map.ofEntries(
        Map.entry("input_cost_per_token",                      new TypeUnit("billed_input_uncached",       "token")),
        Map.entry("output_cost_per_token",                     new TypeUnit("billed_output_text",          "token")),
        Map.entry("cache_read_input_token_cost",               new TypeUnit("billed_input_cache_read",     "token")),
        Map.entry("input_cost_per_token_cache_hit",            new TypeUnit("billed_input_cache_read",     "token")),
        Map.entry("cache_creation_input_token_cost",           new TypeUnit("billed_input_cache_write",    "token")),
        Map.entry("cache_creation_input_token_cost_above_1hr", new TypeUnit("billed_input_cache_write_1h", "token")),
        Map.entry("cache_read_input_audio_token_cost",         new TypeUnit("billed_input_audio_cache_read", "token")),
        Map.entry("cache_creation_input_audio_token_cost",     new TypeUnit("billed_input_audio_cache_write", "token")),
        Map.entry("output_cost_per_reasoning_token",           new TypeUnit("billed_output_reasoning",     "token")),
        Map.entry("input_cost_per_audio_token",                new TypeUnit("billed_input_audio",          "token")),
        Map.entry("output_cost_per_audio_token",               new TypeUnit("billed_output_audio",         "token")),
        Map.entry("input_cost_per_character",                  new TypeUnit("billed_input_characters",     "character")),
        Map.entry("output_cost_per_character",                 new TypeUnit("billed_output_characters",    "character")),
        Map.entry("input_cost_per_request",                    new TypeUnit("billed_requests",             "request")),
        Map.entry("input_cost_per_image",                      new TypeUnit("billed_input_images",         "image")),
        Map.entry("output_cost_per_image",                     new TypeUnit("billed_output_images",        "image")),
        Map.entry("input_cost_per_image_token",                new TypeUnit("billed_input_image_tokens",   "token")),
        Map.entry("output_cost_per_image_token",               new TypeUnit("billed_output_image_tokens",  "token")),
        Map.entry("input_cost_per_pixel",                      new TypeUnit("billed_input_pixels",         "pixel")),
        Map.entry("output_cost_per_pixel",                     new TypeUnit("billed_output_pixels",        "pixel")),
        Map.entry("ocr_cost_per_page",                         new TypeUnit("billed_ocr_pages",            "page")),
        Map.entry("ocr_cost_per_credit",                       new TypeUnit("billed_ocr_credits",          "credit")),
        Map.entry("annotation_cost_per_page",                  new TypeUnit("billed_annotation_pages",     "page")),
        Map.entry("search_context_cost_per_query",             new TypeUnit("billed_search_queries",       "query")),
        Map.entry("input_cost_per_query",                      new TypeUnit("billed_search_queries",       "query")),
        Map.entry("input_cost_per_second",                     new TypeUnit("audio_milliseconds",          "millisecond")),
        Map.entry("input_cost_per_audio_per_second",           new TypeUnit("audio_milliseconds",          "millisecond"))
    );

    // <base>_above_200k_tokens  /  <base>_above_128_tokens
    private static final Pattern CONTEXT_SUFFIX =
        Pattern.compile("^(?<base>.+?)_above_(?<n>\\d+)(?<k>k?)_tokens$");
    // <base>_priority / <base>_flex / <base>_scale / <base>_standard
    private static final Pattern MODE_SUFFIX =
        Pattern.compile("^(?<base>.+?)_(?<mode>priority|flex|scale|standard)$");

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

    /**
     * Refresh prices for a model whose name the caller does not know.
     *
     * Linking a model to a cloud provider is the moment its prices become
     * resolvable, but the link carries only ids. Resolving the name here keeps
     * callers from having to load the model just to trigger a refresh.
     */
    @Async
    public void updatePricesForModelAsync(int modelId) {
        Model model = modelRepository.findById(modelId).orElse(null);
        if (model == null || model.getName() == null || model.getName().isBlank()) {
            log.info("price_updater: model id={} unknown or unnamed, skipping", modelId);
            return;
        }
        updatePricesForModel(modelId, model.getName());
    }

    @Async
    public void updatePricesForModelAsync(int modelId, String modelName) {
        updatePricesForModel(modelId, modelName);
    }

    private void updatePricesForModel(int modelId, String modelName) {
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

        ingestCatalog(modelId, providerId, modelName, data, Instant.now());
    }

    /**
     * Turn a fetched litellm catalog entry into {@code token_prices} rows: map
     * each per-unit price key to a billable quantity + unit, peeling any
     * {@code _priority/_flex/_scale} service-mode suffix and any
     * {@code _above_<N>[k]_tokens} context tier off the key first. Package-private
     * for tests.
     */
    void ingestCatalog(int modelId, int providerId, String modelName,
                       Map<String, Object> data, Instant validFrom) {
        for (Map.Entry<String, Object> entry : data.entrySet()) {
            String rawKey = entry.getKey();
            Object costObj = entry.getValue();
            if (!(costObj instanceof Number)) continue;
            if (rawKey.contains("_batches") || rawKey.contains("_batch")) continue;

            String key = rawKey;
            long minContextTokens = 0L;
            String serviceTier = "default";

            Matcher mode = MODE_SUFFIX.matcher(key);
            if (mode.matches()) {
                String m = mode.group("mode");
                serviceTier = "standard".equals(m) ? "default" : m;
                key = mode.group("base");
            }

            Matcher ctx = CONTEXT_SUFFIX.matcher(key);
            if (ctx.matches()) {
                long n = Long.parseLong(ctx.group("n"));
                minContextTokens = "k".equals(ctx.group("k")) ? n * 1000L : n;
                key = ctx.group("base");
            }

            TypeUnit tu = LITELLM_BASE_KEYS.get(key);
            if (tu == null) continue;

            double cost = ((Number) costObj).doubleValue();
            // A zero is an effective price update too: skipping it would leave
            // the previous non-zero generation active forever. Negative prices
            // are invalid catalogue data and remain ignored.
            if (cost < 0) continue;

            // token/character/flat units: 1e11 = 1e8 micro-cents x 1e3 per-1k.
            // millisecond keeps the historical 1e8 scale (per-1k-ms == per-second).
            double unitScale = "millisecond".equals(tu.unit()) ? 1e8 : 1e11;
            long pricePerK = Math.round(cost * unitScale);

            upsertTokenPrice(modelId, providerId, tu.quantity(), tu.unit(),
                minContextTokens, serviceTier, pricePerK, validFrom);
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
    protected void upsertTokenPrice(int modelId, int providerId, String quantityName, String unit,
                                    long minContextTokens, String serviceTier,
                                    long pricePerK, Instant validFrom) {
        TokenType tokenType = tokenTypeRepository.findByName(quantityName)
            .orElseGet(() -> tokenTypeRepository.save(new TokenType(quantityName)));

        Optional<TokenPrice> latest = tokenPriceRepository
            .findTopByModelIdAndTypeIdAndProviderIdAndUnitAndMinContextTokensAndServiceTierOrderByValidFromDesc(
                modelId, tokenType.getId(), providerId, unit, minContextTokens, serviceTier);

        if (latest.isPresent() && latest.get().getPricePerKUnit() != null
                && latest.get().getPricePerKUnit().longValue() == pricePerK) {
            return;
        }

        // B6: stamp the first row for a triple with the fetch time, like every
        // later row. Back-dating the first-ever price to 2020 is what produced the
        // retroactive 5x overbilling; before the first fetch "no price = free" is
        // the honest answer.
        TokenPrice price = new TokenPrice();
        price.setTypeId(tokenType.getId());
        price.setModelId(modelId);
        price.setProviderId(providerId);
        price.setUnit(unit);
        price.setMinContextTokens(minContextTokens);
        price.setServiceTier(serviceTier);
        price.setValidFrom(validFrom);
        price.setPricePerKUnit(pricePerK);
        tokenPriceRepository.save(price);
    }
}
