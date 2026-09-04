package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
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
        // LiteLLM uses page and credit as alternative names for the same OCR
        // operation. Collapse them so a catalog carrying both cannot bill it twice.
        Map.entry("ocr_cost_per_credit",                       new TypeUnit("billed_ocr_pages",            "page")),
        Map.entry("annotation_cost_per_page",                  new TypeUnit("billed_annotation_pages",     "page")),
        Map.entry("search_context_cost_per_query",             new TypeUnit("billed_search_queries",       "query")),
        Map.entry("input_cost_per_query",                      new TypeUnit("billed_search_queries",       "query")),
        Map.entry("input_cost_per_second",                     new TypeUnit("audio_milliseconds",          "millisecond")),
        Map.entry("input_cost_per_audio_per_second",           new TypeUnit("audio_milliseconds",          "millisecond")),
        Map.entry("output_cost_per_second",                    new TypeUnit("billed_output_milliseconds", "millisecond")),
        Map.entry("output_cost_per_video_per_second",          new TypeUnit("billed_output_milliseconds", "millisecond")),
        Map.entry("output_cost_per_second_1080p",              new TypeUnit("billed_output_milliseconds_1080p", "millisecond")),
        Map.entry("output_cost_per_second_4k",                 new TypeUnit("billed_output_milliseconds_4k", "millisecond")),
        Map.entry("input_cost_per_video_per_second",           new TypeUnit("billed_input_video_milliseconds", "millisecond")),
        Map.entry("output_cost_per_video_token",               new TypeUnit("billed_output_video_tokens", "token")),
        Map.entry("citation_cost_per_token",                   new TypeUnit("billed_citation_tokens", "token")),
        Map.entry("input_dbu_cost_per_token",                  new TypeUnit("billed_input_uncached", "token")),
        Map.entry("output_dbu_cost_per_token",                 new TypeUnit("billed_output_text", "token")),
        Map.entry("google_maps_grounding_cost_per_query",      new TypeUnit("billed_google_maps_queries", "query")),
        Map.entry("code_interpreter_cost_per_session",         new TypeUnit("billed_code_interpreter_sessions", "session"))
    );

    /**
     * Several litellm keys collapse onto one billable quantity (DeepSeek's
     * {@code input_cost_per_token_cache_hit} vs {@code cache_read_input_token_cost};
     * {@code input_cost_per_query} vs {@code search_context_cost_per_query};
     * {@code input_cost_per_second} vs {@code input_cost_per_audio_per_second}).
     * If one catalog entry carries two such keys with different values,
     * persisting both would leave the effective rate at the mercy of row order.
     * The lower number wins; the more specific / canonical key is preferred. An
     * unlisted key is priority 0.
     */
    private static final Map<String, Integer> KEY_PRIORITY = Map.of(
        "input_cost_per_token_cache_hit", 1,
        "input_cost_per_query",           1,
        "input_cost_per_second",          1,
        "output_cost_per_second",         1,
        "ocr_cost_per_credit",            1,
        "input_dbu_cost_per_token",       1,
        "output_dbu_cost_per_token",      1,
        // Legacy image-generation spelling; an explicit output price wins.
        "input_cost_per_image",           1
    );

    /** The identity of one price dimension; aliased catalog keys resolve to the same one. */
    private record PriceDimension(String quantity, String unit, long minContextTokens, String serviceTier) {}
    /** A price value competing to fill a {@link PriceDimension}, tagged with the priority that proposed it. */
    private record PriceCandidate(long pricePerK, int priority) {}

    // <base>_above_200k_tokens  /  <base>_above_128_tokens
    private static final Pattern CONTEXT_SUFFIX =
        Pattern.compile("^(?<base>.+?)_above_(?<n>\\d+)(?<k>k?)_tokens$");
    // <base>_priority / <base>_flex / <base>_scale / <base>_standard
    private static final Pattern MODE_SUFFIX =
        Pattern.compile("^(?<base>.+?)_(?<mode>priority|flex|scale|standard)$");
    private static final Pattern DURATION_INTERVAL_SUFFIX =
        Pattern.compile("^input_cost_per_video_per_second_above_(?<seconds>8|15)s_interval$");

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
        // Resolve every catalog key to its price dimension first, keeping only
        // the highest-priority value per dimension, so two aliased keys can
        // never persist two rows with the same valid_from (which would make the
        // effective rate depend on row order).
        Map<PriceDimension, PriceCandidate> resolved = new HashMap<>();
        boolean searchPerPrompt = "per_prompt".equals(data.get("web_search_billing_unit"));
        for (Map.Entry<String, Object> entry : data.entrySet()) {
            String rawKey = entry.getKey();
            Object costObj = entry.getValue();
            // LiteLLM represents search-context pricing as
            // {low: x, medium: x, high: x}. Preserve low/high as distinct
            // quantities and use the ordinary search quantity for medium, the
            // provider default when the request does not specify a size.
            if ("search_context_cost_per_query".equals(rawKey) && costObj instanceof Map<?, ?> contextPrices) {
                for (String context : List.of("low", "medium", "high")) {
                    Object value = contextPrices.get(context);
                    if (!(value instanceof Number number) || number.doubleValue() < 0) continue;
                    long pricePerK = Math.round(number.doubleValue() * 1e11);
                    PriceDimension dim = new PriceDimension(
                        searchPerPrompt
                            ? ("medium".equals(context) ? "billed_search_prompts" : "billed_search_prompts_" + context)
                            : ("medium".equals(context) ? "billed_search_queries" : "billed_search_queries_" + context),
                        searchPerPrompt ? "request" : "query", 0L, "default");
                    resolved.put(dim, new PriceCandidate(pricePerK, 0));
                }
                continue;
            }
            if ("guardrail_cost_per_unit".equals(rawKey) && costObj instanceof Map<?, ?> unitPrices) {
                for (Map.Entry<?, ?> unitEntry : unitPrices.entrySet()) {
                    if (!(unitEntry.getKey() instanceof String unitName)
                            || !(unitEntry.getValue() instanceof Number number)
                            || number.doubleValue() < 0) continue;
                    PriceDimension dim = new PriceDimension(
                        "billed_guardrail_" + unitName, "unit", 0L, "default");
                    resolved.put(dim, new PriceCandidate(
                        Math.round(number.doubleValue() * 1e11), 0));
                }
                continue;
            }
            if (!(costObj instanceof Number)) {
                if (rawKey.contains("cost") || rawKey.contains("price")) {
                    log.warn("price_updater: unsupported catalogue price field '{}' for '{}'", rawKey, modelName);
                }
                continue;
            }
            if (rawKey.contains("_batches") || rawKey.contains("_batch")) continue;

            Matcher durationInterval = DURATION_INTERVAL_SUFFIX.matcher(rawKey);
            if (durationInterval.matches()) {
                String seconds = durationInterval.group("seconds");
                long pricePerK = Math.round(((Number) costObj).doubleValue() * 1e8);
                resolved.put(new PriceDimension(
                    "billed_input_video_milliseconds_above_" + seconds + "s",
                    "millisecond", 0L, "default"), new PriceCandidate(pricePerK, 0));
                continue;
            }

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
            if (tu == null) {
                if (rawKey.contains("cost") || rawKey.contains("price")) {
                    log.warn("price_updater: unsupported catalogue price field '{}' for '{}'", rawKey, modelName);
                }
                continue;
            }
            if (searchPerPrompt && "billed_search_queries".equals(tu.quantity())) {
                tu = new TypeUnit("billed_search_prompts", "request");
            }
            // LiteLLM's image-generation catalogue historically names the
            // generated-image price input_cost_per_image (notably DALL-E 2/3).
            // Generation responses emit billed_output_images, so route that
            // legacy spelling to the delivered output. Outside generation mode
            // it remains genuine input-image pricing (vision, edits, etc.).
            if ("input_cost_per_image".equals(key)
                    && "image_generation".equals(data.get("mode"))) {
                tu = new TypeUnit("billed_output_images", "image");
            }

            double cost = ((Number) costObj).doubleValue();
            // A zero is an effective price update too: skipping it would leave
            // the previous non-zero generation active forever. Negative prices
            // are invalid catalogue data and remain ignored.
            if (cost < 0) continue;

            // token/character/flat units: 1e11 = 1e8 micro-cents x 1e3 per-1k.
            // millisecond keeps the historical 1e8 scale (per-1k-ms == per-second).
            double unitScale = "millisecond".equals(tu.unit()) ? 1e8 : 1e11;
            long pricePerK = Math.round(cost * unitScale);

            PriceDimension dim = new PriceDimension(tu.quantity(), tu.unit(), minContextTokens, serviceTier);
            int priority = KEY_PRIORITY.getOrDefault(key, 0);
            PriceCandidate existing = resolved.get(dim);
            if (existing == null || priority < existing.priority()) {
                resolved.put(dim, new PriceCandidate(pricePerK, priority));
            }
        }

        for (Map.Entry<PriceDimension, PriceCandidate> e : resolved.entrySet()) {
            PriceDimension dim = e.getKey();
            upsertTokenPrice(modelId, providerId, dim.quantity(), dim.unit(),
                dim.minContextTokens(), dim.serviceTier(), e.getValue().pricePerK(), validFrom);
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
