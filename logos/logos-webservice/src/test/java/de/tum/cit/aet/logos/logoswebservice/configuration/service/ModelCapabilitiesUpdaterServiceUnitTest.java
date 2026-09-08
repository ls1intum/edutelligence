package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelCapabilities;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelCapabilitiesRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;

class ModelCapabilitiesUpdaterServiceUnitTest {

    private ModelCapabilitiesRepository capabilitiesRepository;
    private ModelRepository modelRepository;
    private ModelCapabilitiesUpdaterService svc;

    @BeforeEach
    void setUp() {
        capabilitiesRepository = mock(ModelCapabilitiesRepository.class);
        modelRepository = mock(ModelRepository.class);
        svc = new ModelCapabilitiesUpdaterService(
            null,
            null,
            null,
            new ModelCapabilitiesPersistenceService(capabilitiesRepository, modelRepository)
        );
    }

    /**
     * The persistence layer re-reads the model under a row lock and only writes
     * when the persisted name still is the one the sync resolved against the
     * catalog, so every store test has to say what that persisted name is.
     */
    private void givenModelNamed(String name) {
        Model model = new Model();
        model.setName(name);
        when(modelRepository.findByIdForUpdate(5001)).thenReturn(Optional.of(model));
    }

    // --- normalizeModelName ---

    @Test
    void normalize_nullReturnsNull() {
        assertThat(svc.testNormalizeModelName(null)).isNull();
    }

    @Test
    void normalize_trimsAndLowercases() {
        assertThat(svc.testNormalizeModelName("  GPT-4  ")).isEqualTo("gpt-4");
    }

    @Test
    void normalize_stripsProviderPath() {
        assertThat(svc.testNormalizeModelName("openai/gpt-4")).isEqualTo("gpt-4");
        assertThat(svc.testNormalizeModelName("openrouter/openai/gpt-4")).isEqualTo("gpt-4");
    }

    @Test
    void normalize_stripsTrailingPtOrItSuffix() {
        assertThat(svc.testNormalizeModelName("gpt-4-pt")).isEqualTo("gpt-4");
        assertThat(svc.testNormalizeModelName("llama-3-it")).isEqualTo("llama-3");
    }

    @Test
    void normalize_leavesUnrelatedSuffixesAlone() {
        assertThat(svc.testNormalizeModelName("gpt-4-32k")).isEqualTo("gpt-4-32k");
        assertThat(svc.testNormalizeModelName("gpt-4")).isEqualTo("gpt-4");
    }

    // --- extractModelName ---

    @Test
    void extract_nullOrBlankKeyReturnsNull() {
        assertThat(svc.testExtractModelName(null)).isNull();
        assertThat(svc.testExtractModelName("   ")).isNull();
    }

    @Test
    void extract_plainKeyIsNormalized() {
        assertThat(svc.testExtractModelName("  GPT-4 ")).isEqualTo("gpt-4");
        assertThat(svc.testExtractModelName("gpt-4-pt")).isEqualTo("gpt-4");
    }

    @Test
    void extract_takesLastPathSegment() {
        assertThat(svc.testExtractModelName("azure/gpt-4")).isEqualTo("gpt-4");
        assertThat(svc.testExtractModelName("openrouter/openai/gpt-4")).isEqualTo("gpt-4");
    }

    // --- modelNamesMatch ---

    @Test
    void match_identicalNormalizedNamesMatch() {
        assertThat(svc.testModelNamesMatch("gpt-4", "gpt-4")).isTrue();
    }

    @Test
    void match_isExactNotPrefixOrFuzzy() {
        // matching is an exact equals on the already-normalized names
        assertThat(svc.testModelNamesMatch("gpt-4", "gpt-4-turbo")).isFalse();
        assertThat(svc.testModelNamesMatch("gpt-4", "gpt-4o")).isFalse();
    }

    @Test
    void match_isCaseSensitiveBecauseNormalizationHappensBefore() {
        assertThat(svc.testModelNamesMatch("GPT-4", "gpt-4")).isFalse();
    }

    @Test
    void match_nullSidesNeverMatch() {
        assertThat(svc.testModelNamesMatch(null, "gpt-4")).isFalse();
        assertThat(svc.testModelNamesMatch("gpt-4", null)).isFalse();
        assertThat(svc.testModelNamesMatch(null, null)).isFalse();
    }

    // --- extractAndStoreCapabilities ---

    @Test
    void extractAndStore_singleMatchPersistsFlags() {
        Map<String, Object> catalog = Map.of(
            "openai/gpt-4", Map.of(
                "supports_function_calling", true,
                "supports_vision", false,
                "supports_reasoning", true
            )
        );
        givenModelNamed("gpt-4");

        assertThat(svc.testExtractAndStoreCapabilities(catalog, 5001, "gpt-4")).isTrue();

        verify(capabilitiesRepository).save(argThat((ModelCapabilities c) ->
            c.getModelId() == 5001
                && c.getSupportsFunctionCalling()
                && !c.getSupportsVision()
                && c.getSupportsReasoning()
        ));
    }

    @Test
    void extractAndStore_missingFlagKeysPersistFalse() {
        Map<String, Object> catalog = Map.of(
            "gpt-4", Map.of("max_output_tokens", 8192)
        );
        givenModelNamed("gpt-4");

        assertThat(svc.testExtractAndStoreCapabilities(catalog, 5001, "gpt-4")).isTrue();

        verify(capabilitiesRepository).save(argThat((ModelCapabilities c) ->
            !c.getSupportsFunctionCalling()
                && !c.getSupportsVision()
                && !c.getSupportsReasoning()
        ));
    }

    @Test
    void extractAndStore_multipleMatchesOrTheFlags() {
        Map<String, Object> catalog = new LinkedHashMap<>();
        catalog.put("gpt-4", Map.of("supports_function_calling", true));
        catalog.put("azure/gpt-4", Map.of("supports_vision", true));
        catalog.put("openrouter/openai/gpt-4", Map.of("supports_reasoning", true));
        givenModelNamed("gpt-4");

        assertThat(svc.testExtractAndStoreCapabilities(catalog, 5001, "gpt-4")).isTrue();

        verify(capabilitiesRepository).save(argThat((ModelCapabilities c) ->
            c.getSupportsFunctionCalling()
                && c.getSupportsVision()
                && c.getSupportsReasoning()
        ));
    }

    @Test
    void extractAndStore_unknownModelIsNotStored() {
        Map<String, Object> catalog = Map.of(
            "gpt-4o", Map.of("supports_function_calling", true)
        );
        ModelCapabilities existing = new ModelCapabilities(5001, true, false, true);
        when(capabilitiesRepository.findByModelId(5001)).thenReturn(Optional.of(existing));
        givenModelNamed("gpt-4");

        assertThat(svc.testExtractAndStoreCapabilities(catalog, 5001, "gpt-4")).isFalse();

        verify(capabilitiesRepository, never()).save(any());
        // a pre-existing row must be deleted so the stale flags are not displayed
        verify(capabilitiesRepository).delete(existing);
    }

    @Test
    void extractAndStore_unknownModelWithoutRowIsNoOp() {
        Map<String, Object> catalog = Map.of(
            "gpt-4o", Map.of("supports_function_calling", true)
        );
        when(capabilitiesRepository.findByModelId(5001)).thenReturn(Optional.empty());
        givenModelNamed("gpt-4");

        assertThat(svc.testExtractAndStoreCapabilities(catalog, 5001, "gpt-4")).isFalse();

        verify(capabilitiesRepository, never()).save(any());
        verify(capabilitiesRepository, never()).delete(any());
    }

    @Test
    void extractAndStore_sampleSpecEntryIsSkipped() {
        // a model literally named "sample_spec" must not match the catalog's sample_spec entry
        Map<String, Object> catalog = new LinkedHashMap<>();
        catalog.put("sample_spec", Map.of(
            "supports_function_calling", true,
            "supports_vision", true,
            "supports_reasoning", true
        ));
        catalog.put("gpt-4", Map.of("supports_function_calling", true));

        ModelCapabilities existing = new ModelCapabilities(5001, true, false, true);
        when(capabilitiesRepository.findByModelId(5001)).thenReturn(Optional.of(existing));
        givenModelNamed("sample_spec");

        assertThat(svc.testExtractAndStoreCapabilities(catalog, 5001, "sample_spec")).isFalse();

        verify(capabilitiesRepository, never()).save(any());
        verify(capabilitiesRepository).delete(existing);
    }

    @Test
    void extractAndStore_nonMapEntriesAreSkipped() {
        Map<String, Object> catalog = new LinkedHashMap<>();
        catalog.put("gpt-4", "not-a-model-entry");
        catalog.put("gpt-4o", Map.of("supports_function_calling", true));

        ModelCapabilities existing = new ModelCapabilities(5001, true, false, true);
        when(capabilitiesRepository.findByModelId(5001)).thenReturn(Optional.of(existing));
        givenModelNamed("gpt-4");

        assertThat(svc.testExtractAndStoreCapabilities(catalog, 5001, "gpt-4")).isFalse();

        verify(capabilitiesRepository, never()).save(any());
        verify(capabilitiesRepository).delete(existing);
    }

    @Test
    void extractAndStore_supersededNameKeepsPreviousRow() {
        // A rename that landed after this sync started owns the row: the persisted
        // name no longer matches the name this sync resolved against the catalog,
        // so neither a write nor a delete may touch the row.
        Map<String, Object> catalog = Map.of(
            "openai/gpt-4", Map.of("supports_function_calling", true)
        );
        ModelCapabilities existing = new ModelCapabilities(5001, false, false, false);
        when(capabilitiesRepository.findByModelId(5001)).thenReturn(Optional.of(existing));
        givenModelNamed("gpt-4o");

        assertThat(svc.testExtractAndStoreCapabilities(catalog, 5001, "gpt-4")).isFalse();

        verify(capabilitiesRepository, never()).save(any());
        verify(capabilitiesRepository, never()).delete(any());
    }

    @Test
    void extractAndStore_manualOverrideIsNotOverwrittenOnCatalogMatch() {
        // Even though the catalog matches, an active manual override must keep the row untouched
        Map<String, Object> catalog = Map.of(
            "openai/gpt-4", Map.of(
                "supports_function_calling", false,
                "supports_vision", true,
                "supports_reasoning", true
            )
        );
        ModelCapabilities manual = new ModelCapabilities(5001, true, false, true);
        manual.setManualOverride(true);
        when(capabilitiesRepository.findByModelId(5001)).thenReturn(Optional.of(manual));

        assertThat(svc.testExtractAndStoreCapabilities(catalog, 5001, "gpt-4")).isFalse();

        verify(capabilitiesRepository, never()).save(any());
        verify(capabilitiesRepository, never()).delete(any());
    }

    @Test
    void extractAndStore_manualOverrideSurvivesCatalogNoMatch() {
        // The guard sits before the no-match delete: a manual row outlives a catalog
        // that no longer knows the (renamed) model name
        Map<String, Object> catalog = Map.of(
            "gpt-4o", Map.of("supports_function_calling", true)
        );
        ModelCapabilities manual = new ModelCapabilities(5001, true, false, false);
        manual.setManualOverride(true);
        when(capabilitiesRepository.findByModelId(5001)).thenReturn(Optional.of(manual));

        assertThat(svc.testExtractAndStoreCapabilities(catalog, 5001, "gpt-4")).isFalse();

        verify(capabilitiesRepository, never()).save(any());
        verify(capabilitiesRepository, never()).delete(any());
    }
}
