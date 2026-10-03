package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;

class ModelCapabilitiesUpdaterServiceTest {

    private ModelRepository modelRepository;
    private ModelCapabilitiesPersistenceService persistenceService;
    private ModelCapabilitiesUpdaterService service;

    @BeforeEach
    void setUp() {
        modelRepository = mock(ModelRepository.class);
        persistenceService = mock(ModelCapabilitiesPersistenceService.class);
        // No catalog served yet: tests hand their payload in through
        // serveCatalogFor, which rebuilds the service around it.
        service = new ModelCapabilitiesUpdaterService(
            new ObjectMapper(), mock(ResourceLoader.class), modelRepository, persistenceService);
    }

    private Model model(int id, String name) {
        Model m = mock(Model.class);
        when(m.getId()).thenReturn(id);
        when(m.getName()).thenReturn(name);
        return m;
    }

    @SuppressWarnings("unchecked")
    private void serveCatalogFor(Map<String, Object> catalog) {
        ResourceLoader resourceLoader = mock(ResourceLoader.class);
        Resource resource = mock(Resource.class);
        try {
            when(resourceLoader.getResource(any(String.class))).thenReturn(resource);
            when(resource.getInputStream()).thenReturn(
                new ByteArrayInputStream(new ObjectMapper().writeValueAsBytes(catalog)));
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        service = new ModelCapabilitiesUpdaterService(
            new ObjectMapper(), resourceLoader, modelRepository, persistenceService);
    }

    @Test
    void windowIsTheSmallestAcrossMatchingRegistryEntries() {
        // The bare name and the provider-prefixed entries all match one model
        // (normalization strips the prefix); the request may land on any of
        // them, so the smallest published window is what gets stored.
        Map<String, Object> catalog = Map.of(
            "gpt-5.6-luna", Map.of("max_input_tokens", 1050000, "supports_function_calling", true),
            "azure/us/gpt-5.6-luna", Map.of("max_input_tokens", 1000000));
        Model m = model(7, "gpt-5.6-luna");
        when(modelRepository.findAll()).thenReturn(List.of(m));
        serveCatalogFor(catalog);

        service.updateAllModelCapabilities();

        verify(persistenceService).updateModelCapabilities(7, true, false, false, 1000000);
    }

    @Test
    void modelUnknownToTheCatalogIsNotTouched() {
        Map<String, Object> catalog = Map.of(
            "some-other-model", Map.of("max_input_tokens", 131072));
        Model m = model(7, "never-listed-model");
        when(modelRepository.findAll()).thenReturn(List.of(m));
        serveCatalogFor(catalog);

        service.updateAllModelCapabilities();

        verifyNoInteractions(persistenceService);
    }

    @Test
    void catalogEntryWithoutAWindowStoresNull() {
        // The flags are written whenever the catalog knows the model, and a
        // missing window must clear whatever an older refresh recorded.
        Map<String, Object> catalog = Map.of(
            "windowless-model", Map.of("supports_vision", true));
        Model m = model(3, "windowless-model");
        when(modelRepository.findAll()).thenReturn(List.of(m));
        serveCatalogFor(catalog);

        service.updateAllModelCapabilities();

        verify(persistenceService).updateModelCapabilities(3, false, true, false, null);
    }
}
