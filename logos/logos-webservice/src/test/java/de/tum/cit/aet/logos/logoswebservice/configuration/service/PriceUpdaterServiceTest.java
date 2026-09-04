package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TokenPrice;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TokenType;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TokenPriceRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TokenTypeRepository;

class PriceUpdaterServiceTest {

    private TokenTypeRepository tokenTypeRepository;
    private TokenPriceRepository tokenPriceRepository;
    private PriceUpdaterService service;
    private final List<TokenPrice> saved = new ArrayList<>();

    private record SavedPrice(String type, String unit, long minCtx, String tier, long price) {}

    @BeforeEach
    void setUp() {
        tokenTypeRepository = mock(TokenTypeRepository.class);
        tokenPriceRepository = mock(TokenPriceRepository.class);
        saved.clear();

        when(tokenTypeRepository.findByName(any())).thenAnswer(inv -> {
            TokenType tt = mock(TokenType.class);
            lenient().when(tt.getId()).thenReturn(1);
            lenient().when(tt.getName()).thenReturn(inv.getArgument(0, String.class));
            // stash the name so the saved TokenPrice can be matched back
            return Optional.of(namedType(inv.getArgument(0)));
        });
        when(tokenPriceRepository
            .findTopByModelIdAndTypeIdAndProviderIdAndUnitAndMinContextTokensAndServiceTierOrderByValidFromDesc(
                any(), any(), any(), any(), any(), any()))
            .thenReturn(Optional.empty());
        when(tokenPriceRepository.save(any())).thenAnswer(inv -> {
            saved.add(inv.getArgument(0));
            return inv.getArgument(0);
        });

        service = new PriceUpdaterService(new ObjectMapper(),
            mock(ModelRepository.class), mock(ModelProviderRepository.class),
            mock(ProviderRepository.class), tokenTypeRepository, tokenPriceRepository);
    }

    // findByName is stubbed to return a TokenType carrying its name so we can map
    // a saved TokenPrice (which only holds typeId) back to a readable quantity.
    private final java.util.Map<Integer, String> typeNames = new java.util.HashMap<>();

    private TokenType namedType(String name) {
        int id = typeNames.size() + 1;
        typeNames.put(id, name);
        TokenType tt = new TokenType(name);
        try {
            var f = TokenType.class.getDeclaredField("id");
            f.setAccessible(true);
            f.set(tt, id);
        } catch (ReflectiveOperationException e) {
            throw new RuntimeException(e);
        }
        return tt;
    }

    private List<SavedPrice> ingest(Map<String, Object> catalog) {
        service.ingestCatalog(1, 1, "m", catalog, Instant.parse("2026-09-01T00:00:00Z"));
        return saved.stream()
            .map(p -> new SavedPrice(typeNames.get(p.getTypeId()), p.getUnit(),
                p.getMinContextTokens(), p.getServiceTier(), p.getPricePerKUnit()))
            .toList();
    }

    @Test
    void ingestsCacheWriteCharacterRequestAndTierRows() {
        List<SavedPrice> rows = ingest(Map.ofEntries(
            Map.entry("input_cost_per_token", 2.0e-6),
            Map.entry("output_cost_per_token", 8.0e-6),
            Map.entry("cache_creation_input_token_cost", 2.5e-6),
            Map.entry("cache_creation_input_token_cost_above_1hr", 4.0e-6),
            Map.entry("input_cost_per_token_above_200k_tokens", 4.0e-6),
            Map.entry("output_cost_per_token_flex", 4.0e-6),
            Map.entry("input_cost_per_character", 1.25e-7),
            Map.entry("input_cost_per_pixel", 2.0e-7),
            Map.entry("output_cost_per_pixel", 4.0e-7),
            Map.entry("input_cost_per_request", 5.0e-3),
            Map.entry("input_cost_per_token_cache_hit", 1.0e-7),
            Map.entry("input_cost_per_query", 1.0e-3),
            Map.entry("output_cost_per_image", 4.0e-2),
            Map.entry("input_cost_per_audio_per_second", 1.4e-4),
            Map.entry("output_cost_per_second", 2.4e-4),
            Map.entry("output_cost_per_second_1080p", 3.4e-4),
            Map.entry("input_cost_per_video_per_second", 4.4e-4),
            Map.entry("output_cost_per_video_token", 7.0e-7),
            Map.entry("google_maps_grounding_cost_per_query", 1.4e-2),
            Map.entry("code_interpreter_cost_per_session", 3.0e-2),
            Map.entry("cache_read_input_audio_token_cost", 3.0e-7),
            Map.entry("cache_creation_input_audio_token_cost", 4.0e-7),
            Map.entry("input_cost_per_image_token", 5.0e-7),
            Map.entry("output_cost_per_image_token", 6.0e-7),
            Map.entry("ocr_cost_per_credit", 7.0e-3),
            Map.entry("annotation_cost_per_page", 8.0e-3)
        ));

        assertThat(rows).contains(
            new SavedPrice("billed_input_uncached",       "token",     0,      "default", Math.round(2.0e-6 * 1e11)),
            new SavedPrice("billed_output_text",          "token",     0,      "default", Math.round(8.0e-6 * 1e11)),
            new SavedPrice("billed_input_cache_write",    "token",     0,      "default", Math.round(2.5e-6 * 1e11)),
            new SavedPrice("billed_input_cache_write_1h", "token",     0,      "default", Math.round(4.0e-6 * 1e11)),
            new SavedPrice("billed_input_uncached",       "token",     200000, "default", Math.round(4.0e-6 * 1e11)),
            new SavedPrice("billed_output_text",          "token",     0,      "flex",    Math.round(4.0e-6 * 1e11)),
            new SavedPrice("billed_input_characters",     "character", 0,      "default", Math.round(1.25e-7 * 1e11)),
            new SavedPrice("billed_input_pixels",         "pixel",     0,      "default", Math.round(2.0e-7 * 1e11)),
            new SavedPrice("billed_output_pixels",        "pixel",     0,      "default", Math.round(4.0e-7 * 1e11)),
            new SavedPrice("billed_requests",             "request",     0, "default", Math.round(5.0e-3 * 1e11)),
            new SavedPrice("billed_input_cache_read",     "token",       0, "default", Math.round(1.0e-7 * 1e11)),
            new SavedPrice("billed_search_queries",       "query",       0, "default", Math.round(1.0e-3 * 1e11)),
            new SavedPrice("billed_output_images",        "image",       0, "default", Math.round(4.0e-2 * 1e11)),
            new SavedPrice("audio_milliseconds",          "millisecond", 0, "default", Math.round(1.4e-4 * 1e8)),
            new SavedPrice("billed_output_milliseconds", "millisecond", 0, "default", Math.round(2.4e-4 * 1e8)),
            new SavedPrice("billed_output_milliseconds_1080p", "millisecond", 0, "default", Math.round(3.4e-4 * 1e8)),
            new SavedPrice("billed_input_video_milliseconds", "millisecond", 0, "default", Math.round(4.4e-4 * 1e8)),
            new SavedPrice("billed_output_video_tokens", "token", 0, "default", Math.round(7.0e-7 * 1e11)),
            new SavedPrice("billed_google_maps_queries", "query", 0, "default", Math.round(1.4e-2 * 1e11)),
            new SavedPrice("billed_code_interpreter_sessions", "session", 0, "default", Math.round(3.0e-2 * 1e11)),
            new SavedPrice("billed_input_audio_cache_read", "token", 0, "default", Math.round(3.0e-7 * 1e11)),
            new SavedPrice("billed_input_audio_cache_write", "token", 0, "default", Math.round(4.0e-7 * 1e11)),
            new SavedPrice("billed_input_image_tokens", "token", 0, "default", Math.round(5.0e-7 * 1e11)),
            new SavedPrice("billed_output_image_tokens", "token", 0, "default", Math.round(6.0e-7 * 1e11)),
            new SavedPrice("billed_ocr_pages", "page", 0, "default", Math.round(7.0e-3 * 1e11)),
            new SavedPrice("billed_annotation_pages", "page", 0, "default", Math.round(8.0e-3 * 1e11))
        );
    }

    @Test
    void millisecondUnitKeepsLegacyScale() {
        List<SavedPrice> rows = ingest(Map.of("input_cost_per_second", 6.0e-6));
        assertThat(rows).containsExactly(
            new SavedPrice("audio_milliseconds", "millisecond", 0, "default", Math.round(6.0e-6 * 1e8)));
    }

    @Test
    void expandsStructuredGuardrailUnitPrices() {
        assertThat(ingest(Map.of("guardrail_cost_per_unit", Map.of(
            "contentPolicyUnits", 1.5e-4,
            "topicPolicyUnits", 2.5e-4))))
            .containsExactlyInAnyOrder(
                new SavedPrice("billed_guardrail_contentPolicyUnits", "unit", 0, "default", Math.round(1.5e-4 * 1e11)),
                new SavedPrice("billed_guardrail_topicPolicyUnits", "unit", 0, "default", Math.round(2.5e-4 * 1e11)));
    }

    @Test
    void collapsesEqualStructuredSearchContextPrices() {
        List<SavedPrice> rows = ingest(Map.of(
            "search_context_cost_per_query", Map.of("low", 0.01, "medium", 0.01, "high", 0.01)));
        assertThat(rows).containsExactlyInAnyOrder(
            new SavedPrice("billed_search_queries_low", "query", 0, "default", Math.round(0.01 * 1e11)),
            new SavedPrice("billed_search_queries", "query", 0, "default", Math.round(0.01 * 1e11)),
            new SavedPrice("billed_search_queries_high", "query", 0, "default", Math.round(0.01 * 1e11)));
    }

    @Test
    void preservesDifferentStructuredSearchContextPrices() {
        assertThat(ingest(Map.of(
            "search_context_cost_per_query", Map.of("low", 0.01, "high", 0.02))))
            .containsExactlyInAnyOrder(
                new SavedPrice("billed_search_queries_low", "query", 0, "default", Math.round(0.01 * 1e11)),
                new SavedPrice("billed_search_queries_high", "query", 0, "default", Math.round(0.02 * 1e11)));
    }

    @Test
    void aliasedKeysForOneDimensionPersistExactlyOneRow() {
        // cache_read_input_token_cost and input_cost_per_token_cache_hit both map
        // to billed_input_cache_read; the canonical key wins and only its row is
        // persisted, so the effective rate cannot depend on row order.
        List<SavedPrice> rows = ingest(Map.ofEntries(
            Map.entry("cache_read_input_token_cost", 3.0e-7),
            Map.entry("input_cost_per_token_cache_hit", 9.9e-7),
            Map.entry("search_context_cost_per_query", 1.0e-3),
            Map.entry("input_cost_per_query", 5.0e-3),
            Map.entry("input_cost_per_audio_per_second", 1.4e-4),
            Map.entry("input_cost_per_second", 9.0e-4),
            Map.entry("output_cost_per_video_per_second", 2.4e-4),
            Map.entry("output_cost_per_second", 9.0e-4),
            Map.entry("ocr_cost_per_page", 7.0e-3),
            Map.entry("ocr_cost_per_credit", 9.0e-3)
        ));

        assertThat(rows.stream().filter(r -> r.type().equals("billed_input_cache_read")).toList())
            .containsExactly(new SavedPrice("billed_input_cache_read", "token", 0, "default",
                Math.round(3.0e-7 * 1e11)));
        assertThat(rows.stream().filter(r -> r.type().equals("billed_search_queries")).toList())
            .containsExactly(new SavedPrice("billed_search_queries", "query", 0, "default",
                Math.round(1.0e-3 * 1e11)));
        assertThat(rows.stream().filter(r -> r.type().equals("audio_milliseconds")).toList())
            .containsExactly(new SavedPrice("audio_milliseconds", "millisecond", 0, "default",
                Math.round(1.4e-4 * 1e8)));
        assertThat(rows.stream().filter(r -> r.type().equals("billed_output_milliseconds")).toList())
            .containsExactly(new SavedPrice("billed_output_milliseconds", "millisecond", 0, "default",
                Math.round(2.4e-4 * 1e8)));
        assertThat(rows.stream().filter(r -> r.type().equals("billed_ocr_pages")).toList())
            .containsExactly(new SavedPrice("billed_ocr_pages", "page", 0, "default",
                Math.round(7.0e-3 * 1e11)));
    }

    @Test
    void firstFetchStampsFetchTime_notEpoch() {
        service.ingestCatalog(1, 1, "m", Map.of("input_cost_per_token", 2.0e-6),
            Instant.parse("2026-09-01T00:00:00Z"));
        assertThat(saved).hasSize(1);
        assertThat(saved.get(0).getValidFrom()).isEqualTo(Instant.parse("2026-09-01T00:00:00Z"));
    }

    @Test
    void zeroPriceCreatesGenerationInsteadOfLeavingOldPriceActive() {
        List<SavedPrice> rows = ingest(Map.of("input_cost_per_token", 0.0));
        assertThat(rows).containsExactly(
            new SavedPrice("billed_input_uncached", "token", 0, "default", 0));
    }
    @Test
    void ingestsCitationDbuAndVideoIntervalPrices() {
        List<SavedPrice> rows = ingest(Map.of(
            "citation_cost_per_token", 2.0e-6,
            "input_dbu_cost_per_token", 3.0e-6,
            "output_dbu_cost_per_token", 4.0e-6,
            "input_cost_per_video_per_second_above_8s_interval", 5.0e-4,
            "input_cost_per_video_per_second_above_15s_interval", 6.0e-4
        ));
        assertThat(rows).contains(
            new SavedPrice("billed_citation_tokens", "token", 0, "default", Math.round(2.0e-6 * 1e11)),
            new SavedPrice("billed_input_uncached", "token", 0, "default", Math.round(3.0e-6 * 1e11)),
            new SavedPrice("billed_output_text", "token", 0, "default", Math.round(4.0e-6 * 1e11)),
            new SavedPrice("billed_input_video_milliseconds_above_8s", "millisecond", 0, "default", Math.round(5.0e-4 * 1e8)),
            new SavedPrice("billed_input_video_milliseconds_above_15s", "millisecond", 0, "default", Math.round(6.0e-4 * 1e8))
        );
    }

    @Test
    void perPromptSearchMetadataChangesThePricedQuantity() {
        List<SavedPrice> rows = ingest(Map.of(
            "web_search_billing_unit", "per_prompt",
            "input_cost_per_query", 1.0e-3
        ));
        assertThat(rows).containsExactly(
            new SavedPrice("billed_search_prompts", "request", 0, "default", Math.round(1.0e-3 * 1e11))
        );
    }
}
