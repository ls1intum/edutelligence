package de.tum.cit.aet.logos.logoswebservice.billing;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.concurrent.atomic.AtomicInteger;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

/**
 * Testcontainers checks for the changelog-022 pricing engine: schema shape,
 * {@code logos_resolve_unit_price}, {@code logos_price_usage}, the
 * {@code log_entry_cost} / {@code budget_usage} views, and preservation of price history.
 */
@SpringBootTest
@Testcontainers
class TokenCostFunctionTest {

    @Autowired
    JdbcTemplate jdbc;

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

    // ---------------------------------------------------------------- schema

    @Test
    void migration022_addsColumnsAndCanonicalTypes() {
        assertThat(columnExists("token_prices", "unit")).isTrue();
        assertThat(columnExists("token_prices", "min_context_tokens")).isTrue();
        assertThat(columnExists("token_prices", "service_tier")).isTrue();
        assertThat(columnExists("token_prices", "price_per_k_unit")).isTrue();
        assertThat(columnExists("token_prices", "price_per_k_token")).isFalse();
        assertThat(columnExists("log_entry", "service_tier")).isTrue();
        assertThat(indexExists("log_entry", "idx_log_entry_api_key_timestamp_request")).isTrue();

        Integer newTypes = jdbc.queryForObject(
            "SELECT COUNT(*) FROM token_types WHERE name IN "
            + "('billed_input_uncached','billed_output_text','billed_input_cache_read',"
            + "'billed_input_cache_write','billed_input_cache_write_1h','billed_requests',"
            + "'billed_input_characters','billed_input_images','billed_output_images',"
            + "'billed_input_pixels','billed_output_pixels',"
            + "'billed_ocr_pages','billed_search_queries')", Integer.class);
        assertThat(newTypes).isEqualTo(13);
    }

    // ---------------------------------------------------- resolve_unit_price

    @Test
    void resolveUnitPrice_fallsBackAndPicksTierAndServiceTier() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        seedPrice(model, provider, "billed_input_uncached", "token", 200000, "default", 40000, "2020-01-01");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "flex", 10000, "2020-01-01");

        assertThat(resolve("billed_input_cache_read", model, provider, "2026-01-01", 1000L, null))
            .isEqualTo(20000L);
        assertThat(resolve("billed_input_uncached", model, provider, "2026-01-01", 500000L, null))
            .isEqualTo(40000L);
        assertThat(resolve("billed_input_uncached", model, provider, "2026-01-01", 1000L, "flex"))
            .isEqualTo(10000L);
        assertThat(resolve("billed_output_text", model, provider, "2026-01-01", 1000L, null))
            .isNull();
    }

    @Test
    void resolveUnitPrice_cachedAudioFallsBackTransitivelyToBaseInputRate() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");

        assertThat(resolve("billed_input_audio_cache_read", model, provider,
            "2026-01-01", 1000L, null)).isEqualTo(20000L);
        assertThat(resolve("billed_input_audio_cache_write", model, provider,
            "2026-01-01", 1000L, null)).isEqualTo(20000L);
    }

    // -------------------------------------------------------- price_usage

    @Test
    void priceUsage_openAiInclusive_appliesCacheDiscountOnce() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        seedPrice(model, provider, "billed_input_cache_read", "token", 0, "default", 2000, "2020-01-01");
        seedPrice(model, provider, "billed_output_text", "token", 0, "default", 120000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":1000,\"prompt_cached_tokens\":800,\"completion_tokens\":300}");
        // 200*20000/1000 + 800*2000/1000 + 300*120000/1000
        assertThat(cost).isEqualTo(4000L + 1600L + 36000L);
    }

    @Test
    void priceUsage_openAiInclusive_appliesCacheWritePremiumOnce() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        seedPrice(model, provider, "billed_input_cache_write", "token", 0, "default", 25000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":1000,\"prompt_cache_write_tokens\":200}");
        // Cache writes are a subset of OpenAI/Azure prompt_tokens.
        assertThat(cost).isEqualTo(800L * 20000 / 1000 + 200L * 25000 / 1000);
    }

    @Test
    void priceUsage_anthropicCacheWriteShape_isDisjoint() {
        int model = seedModel();
        int provider = seedCloudProvider("anthropic");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        seedPrice(model, provider, "billed_input_cache_write", "token", 0, "default", 25000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":1000,\"prompt_cache_write_tokens\":200}");
        assertThat(cost).isEqualTo(1000L * 20000 / 1000 + 200L * 25000 / 1000);
    }

    @Test
    void priceUsage_anthropicDisjoint_neverNegative_chargesCacheWrite() {
        int model = seedModel();
        int provider = seedCloudProvider("anthropic");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 30000, "2020-01-01");
        seedPrice(model, provider, "billed_input_cache_read", "token", 0, "default", 3000, "2020-01-01");
        seedPrice(model, provider, "billed_input_cache_write", "token", 0, "default", 37500, "2020-01-01");
        seedPrice(model, provider, "billed_input_cache_write_1h", "token", 0, "default", 60000, "2020-01-01");
        seedPrice(model, provider, "billed_output_text", "token", 0, "default", 150000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":200,\"prompt_cached_tokens\":800,"
            + "\"prompt_cache_write_tokens\":100,\"prompt_cache_write_1h_tokens\":50,"
            + "\"completion_tokens\":400}");
        assertThat(cost).isEqualTo(6000L + 2400L + 3750L + 3000L + 60000L);
    }

    @Test
    void priceUsage_bedrockNativeShape_isDisjointDespiteProviderType() {
        int model = seedModel();
        int provider = seedCloudProvider("bedrock");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 30000, "2020-01-01");
        seedPrice(model, provider, "billed_input_cache_read", "token", 0, "default", 3000, "2020-01-01");
        seedPrice(model, provider, "billed_input_cache_write", "token", 0, "default", 37500, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":200,\"prompt_cached_tokens\":800,"
            + "\"prompt_cache_write_tokens\":100}");
        assertThat(cost).isEqualTo(200L * 30000 / 1000 + 800L * 3000 / 1000
            + 100L * 37500 / 1000);
    }

    @Test
    void priceUsage_bedrockReadOnlyCacheShape_isDisjoint() {
        int model = seedModel();
        int provider = seedCloudProvider("bedrock");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 30000, "2020-01-01");
        seedPrice(model, provider, "billed_input_cache_read", "token", 0, "default", 3000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":200,\"prompt_cached_tokens\":800}");
        assertThat(cost).isEqualTo(200L * 30000 / 1000 + 800L * 3000 / 1000);
    }

    @Test
    void priceUsage_nativeReadOnlyCacheShape_flag_makesItDisjoint() {
        // Native Anthropic cache-read-only turn: cached (100) does not exceed the
        // uncached remainder (1000) and no cache-write count is present, so the
        // usage_shape_disjoint flag the orchestrator sets is the only proof the
        // shape is disjoint. Without it this was billed as 900 uncached + 100
        // read (a bounded undercharge); with it, 1000 uncached + 100 read.
        int model = seedModel();
        int provider = seedCloudProvider("anthropic");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        seedPrice(model, provider, "billed_input_cache_read", "token", 0, "default", 2000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":1000,\"prompt_cached_tokens\":100,\"usage_shape_disjoint\":1}");
        assertThat(cost).isEqualTo(1000L * 20000 / 1000 + 100L * 2000 / 1000);
    }

    @Test
    void priceUsage_disjointFlagIsAuthoritativeWhenProviderTypeIsWrong() {
        // An Anthropic model reached through a custom gateway whose provider row
        // is typed 'openai' (or has no cloud_provider_type). The orchestrator
        // still parsed the native cache spelling and set usage_shape_disjoint;
        // the flag alone must drive the disjoint decomposition, so the small
        // cache-read-only turn is not undercharged.
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        seedPrice(model, provider, "billed_input_cache_read", "token", 0, "default", 2000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":1000,\"prompt_cached_tokens\":100,\"usage_shape_disjoint\":1}");
        assertThat(cost).isEqualTo(1000L * 20000 / 1000 + 100L * 2000 / 1000);
    }

    @Test
    void priceUsage_ocrCreditsSuppressedWhenPagesArePriced() {
        // OCR is derived as both billed_ocr_pages and billed_ocr_credits (one
        // credit per page). A catalogue that prices pages must not also be
        // charged the identical credit count.
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_ocr_pages", "page", 0, "default", 1000, "2020-01-01");
        seedPrice(model, provider, "billed_ocr_credits", "credit", 0, "default", 1000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"billed_ocr_pages\":3,\"billed_ocr_credits\":3}");
        assertThat(cost).isEqualTo(3L * 1000 / 1000);
    }

    @Test
    void priceUsage_ocrCreditsChargedWhenOnlyCreditPriceExists() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_ocr_credits", "credit", 0, "default", 1000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"billed_ocr_pages\":3,\"billed_ocr_credits\":3}");
        assertThat(cost).isEqualTo(3L * 1000 / 1000);
    }

    @Test
    void priceUsage_anthropicViaOpenAiCompatibleSurface_appliesCacheDiscountOnce() {
        // cloud_provider_type is 'anthropic', but the model is reached through an
        // OpenAI-compatible gateway: prompt_tokens is inclusive (contains the
        // cached tokens) and there is no cache-write counter. The decomposition
        // must not treat this as the disjoint native shape -- doing so bills the
        // cached tokens at the full input rate AND the cache-read rate (#892 B1).
        int model = seedModel();
        int provider = seedCloudProvider("anthropic");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        seedPrice(model, provider, "billed_input_cache_read", "token", 0, "default", 2000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":1000,\"prompt_cached_tokens\":800}");
        // 200 uncached + 800 cache-read, not 1000 uncached + 800 cache-read.
        assertThat(cost).isEqualTo(200L * 20000 / 1000 + 800L * 2000 / 1000);
    }

    @Test
    void priceUsage_reasoningWithoutOwnPrice_billedOnceAtOutputRate() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        seedPrice(model, provider, "billed_output_text", "token", 0, "default", 120000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":832,\"completion_tokens\":319,\"completion_reasoning_tokens\":170}");
        assertThat(cost).isEqualTo(16640L + 38280L);
    }

    @Test
    void priceUsage_perCharacterModel_ignoresTokenQuantities() {
        int model = seedModel();
        int provider = seedCloudProvider("gemini");
        seedPrice(model, provider, "billed_input_characters", "character", 0, "default", 125, "2020-01-01");
        seedPrice(model, provider, "billed_output_characters", "character", 0, "default", 375, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":1000,\"completion_tokens\":500,"
            + "\"billed_input_characters\":4000,\"billed_output_characters\":2000}");
        assertThat(cost).isEqualTo(4000L * 125 / 1000 + 2000L * 375 / 1000);
    }

    @Test
    void priceUsage_suppressesCharacterFallbackPerDirection() {
        int model = seedModel();
        int provider = seedCloudProvider("gemini");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        seedPrice(model, provider, "billed_output_characters", "character", 0, "default", 375, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":1000,\"completion_tokens\":0,"
            + "\"billed_input_characters\":4000,\"billed_output_characters\":2000}");
        assertThat(cost).isEqualTo(1000L * 20000 / 1000 + 2000L * 375 / 1000);
    }

    @Test
    void priceUsage_keepsInputAndOutputPixelsDistinct() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_input_pixels", "pixel", 0, "default", 100, "2020-01-01");
        seedPrice(model, provider, "billed_output_pixels", "pixel", 0, "default", 300, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"billed_input_pixels\":2000,\"billed_output_pixels\":4000}");
        assertThat(cost).isEqualTo(2000L * 100 / 1000 + 4000L * 300 / 1000);
    }

    @Test
    void priceUsage_decomposesImageTokensAndCachedAudio() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        seedPrice(model, provider, "billed_input_audio_cache_read", "token", 0, "default", 1000, "2020-01-01");
        seedPrice(model, provider, "billed_input_image_tokens", "token", 0, "default", 30000, "2020-01-01");
        seedPrice(model, provider, "billed_output_text", "token", 0, "default", 120000, "2020-01-01");
        seedPrice(model, provider, "billed_output_image_tokens", "token", 0, "default", 150000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":1000,\"prompt_cached_tokens\":100,\"prompt_audio_tokens\":100,"
            + "\"prompt_cache_read_audio_tokens\":100,\"prompt_image_tokens\":200,"
            + "\"completion_tokens\":500,\"completion_image_tokens\":100}");
        assertThat(cost).isEqualTo(
            700L * 20000 / 1000 + 100L * 1000 / 1000 + 200L * 30000 / 1000
            + 400L * 120000 / 1000 + 100L * 150000 / 1000);
    }

    @Test
    void priceUsage_pricesOutputImagesAsTheirOwnDimension() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_output_images", "image", 0, "default", 40_000_000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"billed_output_images\":2}");
        assertThat(cost).isEqualTo(2L * 40_000_000 / 1000);
    }

    @Test
    void priceUsage_flatRequestFee_alwaysApplies() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        seedPrice(model, provider, "billed_output_text", "token", 0, "default", 120000, "2020-01-01");
        seedPrice(model, provider, "billed_requests", "request", 0, "default", 5_000_000, "2020-01-01");

        Long cost = price(model, provider, "2026-01-01", null,
            "{\"prompt_tokens\":10,\"completion_tokens\":10,\"billed_requests\":1}");
        assertThat(cost).isEqualTo(10L * 20000 / 1000 + 10L * 120000 / 1000 + 1L * 5_000_000 / 1000);
    }

    @Test
    void priceUsage_localProviderReturnsNull_andCloudWithoutPricesReturnsNull() {
        int model = seedModel();
        int local = seedLocalProvider();
        assertThat(price(model, local, "2026-01-01", null,
            "{\"prompt_tokens\":10,\"completion_tokens\":10}")).isNull();

        int cloudNoPrices = seedCloudProvider("openai");
        assertThat(price(model, cloudNoPrices, "2026-01-01", null,
            "{\"prompt_tokens\":10,\"completion_tokens\":10}")).isNull();
    }

    @Test
    void priceUsage_citationTokensAreAnIndependentDimension() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_citation_tokens", "token", 0, "default", 7000, "2020-01-01");
        assertThat(price(model, provider, "2026-01-01", null,
            "{\"citation_tokens\":300}")).isEqualTo(2100L);
    }

    @Test
    void priceUsage_usesOnlyHighestApplicableVideoDurationTier() {
        int model = seedModel();
        int provider = seedCloudProvider("gemini");
        seedPrice(model, provider, "billed_input_video_milliseconds", "millisecond", 0, "default", 100, "2020-01-01");
        seedPrice(model, provider, "billed_input_video_milliseconds_above_8s", "millisecond", 0, "default", 200, "2020-01-01");
        seedPrice(model, provider, "billed_input_video_milliseconds_above_15s", "millisecond", 0, "default", 300, "2020-01-01");
        assertThat(price(model, provider, "2026-01-01", null,
            "{\"billed_input_video_milliseconds\":16000,"
            + "\"billed_input_video_milliseconds_above_8s\":16000,"
            + "\"billed_input_video_milliseconds_above_15s\":16000}"))
            .isEqualTo(16000L * 300 / 1000);
    }

    @Test
    void priceUsage_perPromptSearchDoesNotAlsoChargeQueries() {
        int model = seedModel();
        int provider = seedCloudProvider("gemini");
        seedPrice(model, provider, "billed_search_prompts", "request", 0, "default", 5000, "2020-01-01");
        assertThat(price(model, provider, "2026-01-01", null,
            "{\"billed_search_queries\":3,\"billed_search_prompts\":1}"))
            .isEqualTo(5L);
    }

    @Test
    void priceUsage_highContextSearchFallsBackToScalarSearchPrice() {
        // The catalogue carries only the scalar search-query price; a request that
        // asked for a high context size still bills at that rate rather than free.
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_search_queries", "query", 0, "default", 1_000_000, "2020-01-01");
        assertThat(price(model, provider, "2026-01-01", null, "{\"billed_search_queries_high\":3}"))
            .isEqualTo(3L * 1_000_000 / 1000);
    }

    @Test
    void priceUsage_sizeSpecificSearchPriceStillWinsWhenPresent() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_search_queries", "query", 0, "default", 1_000_000, "2020-01-01");
        seedPrice(model, provider, "billed_search_queries_high", "query", 0, "default", 3_000_000, "2020-01-01");
        assertThat(price(model, provider, "2026-01-01", null, "{\"billed_search_queries_high\":2}"))
            .isEqualTo(2L * 3_000_000 / 1000);
    }

    @Test
    void priceUsage_highContextSearchPromptFallsBackToScalarPromptPrice() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_search_prompts", "request", 0, "default", 25_000_000, "2020-01-01");
        assertThat(price(model, provider, "2026-01-01", null, "{\"billed_search_prompts_high\":1}"))
            .isEqualTo(25_000_000L / 1000);
    }

    // --------------------------------------------------------------- views

    @Test
    void budgetUsageAndLogEntryCost_agreeAndUseTheFunction() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        seedPrice(model, provider, "billed_output_text", "token", 0, "default", 120000, "2020-01-01");
        int apiKey = seedApiKey(seedTeam());
        int le = seedLogEntry(apiKey, model, provider, "2026-05-10T12:00:00Z");
        // usage_tokens holds the raw extract_token_usage vocabulary, not the
        // pre-decomposed billed_* quantities — logos_price_usage decomposes.
        seedUsageToken(le, "prompt_tokens", 1000);
        seedUsageToken(le, "completion_tokens", 200);

        Long viaLec = jdbc.queryForObject(
            "SELECT cost_micro_cents FROM log_entry_cost WHERE log_entry_id = ?", Long.class, le);
        Long viaBudget = jdbc.queryForObject(
            "SELECT cost_micro_cents FROM budget_usage WHERE api_key_id = ? AND month = DATE '2026-05-01'",
            Long.class, apiKey);
        assertThat(viaLec).isEqualTo(1000L * 20000 / 1000 + 200L * 120000 / 1000);
        assertThat(viaBudget).isEqualTo(viaLec);
    }

    @Test
    void logEntryCost_failedRequest_billsDeliveredOutputButNotTheRequestFee() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        // The provider still billed Logos for the 40 output tokens the stream
        // produced before it dropped; the flat per-request fee is not owed.
        seedPrice(model, provider, "billed_requests", "request", 0, "default", 5000, "2020-01-01");
        seedPrice(model, provider, "billed_output_text", "token", 0, "default", 120000, "2020-01-01");
        int apiKey = seedApiKey(seedTeam());
        int le = seedLogEntry(apiKey, model, provider, "2026-05-10T12:00:00Z", "error");
        seedUsageToken(le, "billed_requests", 1);
        seedUsageToken(le, "completion_tokens", 40);

        Long viaLec = jdbc.queryForObject(
            "SELECT cost_micro_cents FROM log_entry_cost WHERE log_entry_id = ?", Long.class, le);
        assertThat(viaLec).isEqualTo(40L * 120000 / 1000);
    }

    @Test
    void logEntryCost_failedRequest_doesNotBillRequestDerivedInputEstimates() {
        int model = seedModel();
        int provider = seedCloudProvider("gemini");
        // A character-priced model whose request text was measured but rejected:
        // billed_input_characters describes what the caller sent, not consumption.
        seedPrice(model, provider, "billed_input_characters", "character", 0, "default", 100, "2020-01-01");
        int apiKey = seedApiKey(seedTeam());
        int le = seedLogEntry(apiKey, model, provider, "2026-05-10T12:00:00Z", "error");
        seedUsageToken(le, "billed_input_characters", 4000);

        Long viaLec = jdbc.queryForObject(
            "SELECT cost_micro_cents FROM log_entry_cost WHERE log_entry_id = ?", Long.class, le);
        assertThat(viaLec).isNull();
    }

    @Test
    void logEntryCost_failedGeneration_doesNotBillTheRequestedImageOrDurationCount() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        // derive_billable_quantities falls back to the requested n / duration when
        // the response has no data; a rejected generation delivered none of it.
        seedPrice(model, provider, "billed_output_images", "image", 0, "default", 40_000_000, "2020-01-01");
        seedPrice(model, provider, "billed_output_pixels", "pixel", 0, "default", 1, "2020-01-01");
        seedPrice(model, provider, "billed_output_milliseconds", "millisecond", 0, "default", 200, "2020-01-01");
        int apiKey = seedApiKey(seedTeam());
        int le = seedLogEntry(apiKey, model, provider, "2026-05-10T12:00:00Z", "error");
        seedUsageToken(le, "billed_output_images", 4);
        seedUsageToken(le, "billed_output_pixels", 4 * 1024 * 1024);
        seedUsageToken(le, "billed_output_milliseconds", 8000);

        Long viaLec = jdbc.queryForObject(
            "SELECT cost_micro_cents FROM log_entry_cost WHERE log_entry_id = ?", Long.class, le);
        assertThat(viaLec).isNull();
    }

    @Test
    void logEntryCost_inFlightRequestIsNotPricedUntilItFinishes() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_output_text", "token", 0, "default", 120000, "2020-01-01");
        int apiKey = seedApiKey(seedTeam());
        int le = seedLogEntry(apiKey, model, provider, "2026-05-10T12:00:00Z", (String) null);
        seedUsageToken(le, "completion_tokens", 40);

        Long viaLec = jdbc.queryForObject(
            "SELECT cost_micro_cents FROM log_entry_cost WHERE log_entry_id = ?", Long.class, le);
        assertThat(viaLec).isNull();
    }

    @Test
    void tokenPriceGapsMapsRawUsageToCanonicalQuantity() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        int le = seedLogEntry(seedApiKey(seedTeam()), model, provider, "2026-05-10T12:00:00Z");
        seedUsageToken(le, "prompt_tokens", 321);

        Integer gaps = jdbc.queryForObject(
            "SELECT COUNT(*) FROM token_price_gaps WHERE model_id = ? AND provider_id = ? "
            + "AND quantity = 'billed_input_uncached' AND tokens = 321",
            Integer.class, model, provider);
        assertThat(gaps).isEqualTo(1);
    }

    @Test
    void tokenPriceGaps_ignoresCharactersSuppressedByTokenPricing() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2020-01-01");
        int le = seedLogEntry(seedApiKey(seedTeam()), model, provider, "2026-05-10T12:00:00Z");
        seedUsageToken(le, "billed_input_characters", 321);

        Integer gaps = jdbc.queryForObject(
            "SELECT COUNT(*) FROM token_price_gaps WHERE model_id = ? AND provider_id = ? "
            + "AND quantity = 'billed_input_characters'",
            Integer.class, model, provider);
        assertThat(gaps).isZero();
    }

    // ------------------------------------------------------ price history

    @Test
    void collapsePriceSentinelsRepricesSyntheticHistoryFromEarliestCorrection() {
        int model = seedModel();
        int provider = seedCloudProvider("openai");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 100000, "2020-01-01");
        seedPrice(model, provider, "billed_input_uncached", "token", 0, "default", 20000, "2026-08-05");

        Integer changed = jdbc.queryForObject(
            "SELECT logos_collapse_price_sentinels()", Integer.class);

        Integer rows = jdbc.queryForObject(
            "SELECT COUNT(*) FROM token_prices tp JOIN token_types t ON t.id = tp.type_id "
            + "WHERE tp.model_id = ? AND t.name = 'billed_input_uncached'", Integer.class, model);
        assertThat(changed).isEqualTo(1);
        assertThat(rows).isEqualTo(1);
        Long historical = resolve("billed_input_uncached", model, provider, "2021-01-01", 1L, null);
        Long current = resolve("billed_input_uncached", model, provider, "2026-09-01", 1L, null);
        assertThat(historical).isEqualTo(20000L);
        assertThat(current).isEqualTo(20000L);

        assertThat(jdbc.queryForObject(
            "SELECT logos_collapse_price_sentinels()", Integer.class)).isZero();
    }

    // --------------------------------------------------------------- helpers

    private Long resolve(String q, int model, int provider, String at, Long ctx, String tier) {
        return jdbc.queryForObject(
            "SELECT logos_resolve_unit_price(?, ?, ?, ?::timestamptz, ?, ?)",
            Long.class, q, model, provider, at, ctx, tier);
    }

    private Long price(int model, int provider, String at, String tier, String usageJson) {
        return jdbc.queryForObject(
            "SELECT logos_price_usage(?, ?, ?::timestamptz, ?, ?::jsonb)",
            Long.class, model, provider, at, tier, usageJson);
    }

    private int seedModel() {
        return jdbc.queryForObject(
            "INSERT INTO models (name) VALUES (?) RETURNING id",
            Integer.class, "m-" + SEQ.getAndIncrement());
    }

    private int seedCloudProvider(String cloudType) {
        return jdbc.queryForObject(
            "INSERT INTO providers (name, base_url, provider_type, cloud_provider_type, auth_name, auth_format) "
            + "VALUES (?, 'http://x', 'cloud', CAST(? AS cloud_provider_type_enum), 'Authorization', 'Bearer %s') "
            + "RETURNING id",
            Integer.class, "p-" + SEQ.getAndIncrement(), cloudType);
    }

    private int seedLocalProvider() {
        return jdbc.queryForObject(
            "INSERT INTO providers (name, base_url, provider_type, auth_name, auth_format) "
            + "VALUES (?, 'http://x', 'logosnode', 'Authorization', 'Bearer %s') RETURNING id",
            Integer.class, "p-" + SEQ.getAndIncrement());
    }

    private int seedTeam() {
        return jdbc.queryForObject(
            "INSERT INTO teams (name) VALUES (?) RETURNING id",
            Integer.class, "t-" + SEQ.getAndIncrement());
    }

    private int seedApiKey(int teamId) {
        return jdbc.queryForObject(
            "INSERT INTO api_keys (key_value, name, team_id) VALUES (?, ?, ?) RETURNING id",
            Integer.class, "lg-" + SEQ.getAndIncrement(), "k-" + SEQ.get(), teamId);
    }

    private int seedLogEntry(int apiKeyId, int modelId, int providerId, String tsRequest) {
        return seedLogEntry(apiKeyId, modelId, providerId, tsRequest, "success");
    }

    private int seedLogEntry(int apiKeyId, int modelId, int providerId, String tsRequest, String resultStatus) {
        return jdbc.queryForObject(
            "INSERT INTO log_entry (timestamp_request, api_key_id, model_id, provider_id, result_status) "
            + "VALUES (?::timestamptz, ?, ?, ?, ?::result_status_enum) RETURNING id",
            Integer.class, tsRequest, apiKeyId, modelId, providerId, resultStatus);
    }

    private void seedUsageToken(int logEntryId, String typeName, long count) {
        jdbc.update("INSERT INTO token_types (name) VALUES (?) ON CONFLICT (name) DO NOTHING", typeName);
        Integer typeId = jdbc.queryForObject(
            "SELECT id FROM token_types WHERE name = ?", Integer.class, typeName);
        jdbc.update("INSERT INTO usage_tokens (type_id, log_entry_id, token_count) VALUES (?, ?, ?)",
            typeId, logEntryId, count);
    }

    private void seedPrice(int modelId, int providerId, String typeName, String unit,
                           long minContextTokens, String serviceTier, long pricePerKUnit, String validFrom) {
        String tsz = (validFrom.endsWith("Z") || validFrom.contains("+"))
            ? validFrom : validFrom + "T00:00:00Z";
        jdbc.update("INSERT INTO token_types (name) VALUES (?) ON CONFLICT (name) DO NOTHING", typeName);
        Integer typeId = jdbc.queryForObject(
            "SELECT id FROM token_types WHERE name = ?", Integer.class, typeName);
        jdbc.update(
            "INSERT INTO token_prices (type_id, model_id, provider_id, unit, min_context_tokens, "
            + "service_tier, valid_from, price_per_k_unit) VALUES (?, ?, ?, ?, ?, ?, ?::timestamptz, ?)",
            typeId, modelId, providerId, unit, minContextTokens, serviceTier, tsz, pricePerKUnit);
    }

    private boolean columnExists(String table, String col) {
        Integer n = jdbc.queryForObject(
            "SELECT COUNT(*) FROM information_schema.columns "
            + "WHERE table_schema = 'public' AND table_name = ? AND column_name = ?",
            Integer.class, table, col);
        return n != null && n > 0;
    }

    private boolean indexExists(String table, String index) {
        Integer n = jdbc.queryForObject(
            "SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'public' "
            + "AND tablename = ? AND indexname = ?",
            Integer.class, table, index);
        return n != null && n > 0;
    }
}
