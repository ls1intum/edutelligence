package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelCapabilities;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelCapabilitiesRepository;

@Service
public class ModelCapabilitiesPersistenceService {

    private final ModelCapabilitiesRepository modelCapabilitiesRepository;

    public ModelCapabilitiesPersistenceService(
            ModelCapabilitiesRepository modelCapabilitiesRepository) {
        this.modelCapabilitiesRepository = modelCapabilitiesRepository;
    }

    @Transactional
    public void updateModelCapabilities(
            int modelId,
            boolean supportsFunctionCalling,
            boolean supportsVision,
            boolean supportsReasoning,
            Integer maxInputTokens) {

        ModelCapabilities capabilities = modelCapabilitiesRepository.findByModelId(modelId)
            .orElseGet(() -> {
                ModelCapabilities newCap = new ModelCapabilities();
                newCap.setModelId(modelId);
                return newCap;
            });

        capabilities.setSupportsFunctionCalling(supportsFunctionCalling);
        capabilities.setSupportsVision(supportsVision);
        capabilities.setSupportsReasoning(supportsReasoning);
        // Set unconditionally, including null: a registry refresh that drops
        // the model's window must clear a value an older refresh recorded.
        capabilities.setMaxInputTokens(maxInputTokens);

        modelCapabilitiesRepository.save(capabilities);
    }

    @Transactional
    public void deleteModelCapabilities(int modelId) {

        modelCapabilitiesRepository.findByModelId(modelId)
            .ifPresent(modelCapabilitiesRepository::delete);
    }
}
