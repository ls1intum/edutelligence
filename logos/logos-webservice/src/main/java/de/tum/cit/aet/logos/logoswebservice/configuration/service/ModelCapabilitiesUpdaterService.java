package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.io.InputStream;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;
import org.springframework.scheduling.annotation.Async;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.databind.ObjectMapper;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelCapabilities;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelCapabilitiesRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;

@Service
public class ModelCapabilitiesUpdaterService {

    private static final Logger log = LoggerFactory.getLogger(ModelCapabilitiesUpdaterService.class);
    
    private static final String LOCAL_JSON_PATH = "classpath:model_prices_and_context_window.json";

    private final ObjectMapper objectMapper;
    private final ResourceLoader resourceLoader;
    private final ModelRepository modelRepository;
    private final ModelCapabilitiesRepository modelCapabilitiesRepository; 

    public ModelCapabilitiesUpdaterService(ObjectMapper objectMapper,
                                           ResourceLoader resourceLoader,
                                           ModelRepository modelRepository,
                                           ModelProviderRepository modelProviderRepository,
                                           ProviderRepository providerRepository,
                                           ModelCapabilitiesRepository modelCapabilitiesRepository) {
        this.objectMapper = objectMapper;
        this.resourceLoader = resourceLoader;
        this.modelRepository = modelRepository;
        this.modelCapabilitiesRepository = modelCapabilitiesRepository;
    }

    @Scheduled(initialDelay = 0, fixedDelay = 86_400_000)
    public void updateAllModelCapabilities() {
        log.info("capabilities_updater: starting local catalog refresh for all models");
        
        Map<String, Object> fullCatalog = loadLocalCatalog();
        if (fullCatalog == null || fullCatalog.isEmpty()) {
            log.error("capabilities_updater: local JSON catalog could not be loaded or is empty!");
            return;
        }

        List<Model> allModels = modelRepository.findAll();
        if (allModels.isEmpty()) {
            log.info("capabilities_updater: no models found in database, nothing to refresh");
            return;
        }

        int count = 0;
        for (Model model : allModels) {
            if (model.getName() == null || model.getName().isBlank()) continue;
            
            try {
                boolean success = extractAndStoreCapabilities(fullCatalog, model.getId(), model.getName());
                if (success) count++;
            } catch (Exception e) {
                log.warn("capabilities_updater: failed for '{}' (id={}): {}", model.getName(), model.getId(), e.getMessage());
            }
        }
        log.info("capabilities_updater: local refresh complete ({} models updated)", count);
    }


    @Async
    public void updateCapabilitiesForModelAsync(int modelId, String modelName) {
        Map<String, Object> fullCatalog = loadLocalCatalog();
        if (fullCatalog == null) return;

        try {
            extractAndStoreCapabilities(fullCatalog, modelId, modelName);
        } catch (Exception e) {
            log.warn("capabilities_updater: async sync failed for model '{}' (id={}): {}", modelName, modelId, e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    private boolean extractAndStoreCapabilities(
            Map<String, Object> catalog,
            int modelId,
            String modelName) {
    
        String normalizedModelName = normalizeModelName(modelName);
        boolean found = false;
        boolean supportsFunctionCalling = false;
        boolean supportsVision = false;
        boolean supportsReasoning = false;
    
        for (Map.Entry<String, Object> entry : catalog.entrySet()) {
            String catalogKey = entry.getKey();
    
            if (catalogKey == null || !(entry.getValue() instanceof Map)) {
                continue;
            }
    
            String catalogModelName = extractModelName(catalogKey);
            if (catalogModelName == null) {
                continue;
            }
    
            if (!modelNamesMatch(normalizedModelName, catalogModelName)) {
                continue;
            }
    
            Map<String, Object> modelData = (Map<String, Object>) entry.getValue();
            found = true;
            supportsFunctionCalling |= Boolean.TRUE.equals(
                modelData.get("supports_function_calling")
            );
    
            supportsVision |= Boolean.TRUE.equals(
                modelData.get("supports_vision")
            );
    
            supportsReasoning |= Boolean.TRUE.equals(
                modelData.get("supports_reasoning")
            );
    
            log.debug(
                "capabilities_updater: matched '{}' for model '{}'",
                catalogKey,
                modelName
            );
        }
    
        if (!found) {
            log.debug(
                "capabilities_updater: model '{}' not found in local JSON registry",
                modelName
            );
            return false;
        }
    
        Map<String, Object> mergedCapabilities = new HashMap<>();
        mergedCapabilities.put(
            "supports_function_calling",
            supportsFunctionCalling
        );
        mergedCapabilities.put(
            "supports_vision",
            supportsVision
        );
        mergedCapabilities.put(
            "supports_reasoning",
            supportsReasoning
        );
    
        updateModelCapabilities(modelId, mergedCapabilities);
    
        return true;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> loadLocalCatalog() {
        try {
            Resource resource = resourceLoader.getResource(LOCAL_JSON_PATH);
            try (InputStream is = resource.getInputStream()) {
                return objectMapper.readValue(is, Map.class);
            }
        } catch (Exception e) {
            log.error("capabilities_updater: failed to read local registry file from " + LOCAL_JSON_PATH, e);
            return null;
        }
    }

    @Transactional
    protected void updateModelCapabilities(int modelId, Map<String, Object> data) {
        ModelCapabilities capabilities = modelCapabilitiesRepository.findByModelId(modelId)
            .orElseGet(() -> {
                ModelCapabilities newCap = new ModelCapabilities();
                newCap.setModelId(modelId);
                return newCap;
            });
        capabilities.setSupportsFunctionCalling(Boolean.TRUE.equals(data.get("supports_function_calling")));
        capabilities.setSupportsVision(Boolean.TRUE.equals(data.get("supports_vision")));
        capabilities.setSupportsReasoning(Boolean.TRUE.equals(data.get("supports_reasoning")));

        modelCapabilitiesRepository.save(capabilities);
    }

    private String extractModelName(String catalogKey) {
        if (catalogKey == null || catalogKey.isBlank()) {
            return null;
        }

        String key = catalogKey.trim().toLowerCase(Locale.ROOT);

        int lastSlash = key.lastIndexOf('/');

        String modelName = lastSlash >= 0
            ? key.substring(lastSlash + 1)
            : key;

        return normalizeModelName(modelName);
    }

    private String normalizeModelName(String modelName) {
        if (modelName == null) {
            return null;
        }

        String normalized = modelName.trim().toLowerCase(Locale.ROOT);

        int lastSlash = normalized.lastIndexOf('/');
        if (lastSlash >= 0) {
            normalized = normalized.substring(lastSlash + 1);
        }

        normalized = normalized.replaceFirst("-(pt|it)$", "");

        return normalized;
    }

    private boolean modelNamesMatch(
            String requestedModelName,
            String catalogModelName) {

        if (requestedModelName == null || catalogModelName == null) {
            return false;
        }

        return requestedModelName.equals(catalogModelName);
    }
}
