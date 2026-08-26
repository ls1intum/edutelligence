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
            boolean supportsReasoning) {

        ModelCapabilities capabilities = modelCapabilitiesRepository.findByModelId(modelId)
            .orElseGet(() -> {
                ModelCapabilities newCap = new ModelCapabilities();
                newCap.setModelId(modelId);
                return newCap;
            });

        capabilities.setSupportsFunctionCalling(supportsFunctionCalling);
        capabilities.setSupportsVision(supportsVision);
        capabilities.setSupportsReasoning(supportsReasoning);

        modelCapabilitiesRepository.save(capabilities);
    }

    @Transactional
    public void deleteModelCapabilities(int modelId) {

        modelCapabilitiesRepository.findByModelId(modelId)
            .ifPresent(modelCapabilitiesRepository::delete);
    }

    @Transactional
    public boolean isManualOverride(int modelId) {

        return modelCapabilitiesRepository.findByModelId(modelId)
            .map(ModelCapabilities::getManualOverride)
            .orElse(false);
    }

    @Transactional
    public void setManualCapabilities(
            int modelId,
            boolean supportsFunctionCalling,
            boolean supportsVision,
            boolean supportsReasoning) {

        ModelCapabilities capabilities = modelCapabilitiesRepository.findByModelId(modelId)
            .orElseGet(() -> {
                ModelCapabilities newCap = new ModelCapabilities();
                newCap.setModelId(modelId);
                return newCap;
            });

        capabilities.setSupportsFunctionCalling(supportsFunctionCalling);
        capabilities.setSupportsVision(supportsVision);
        capabilities.setSupportsReasoning(supportsReasoning);
        capabilities.setManualOverride(true);

        modelCapabilitiesRepository.save(capabilities);
    }

    @Transactional
    public void clearManualOverride(int modelId) {

        modelCapabilitiesRepository.findByModelId(modelId)
            .ifPresent(capabilities -> {
                capabilities.setManualOverride(false);
                modelCapabilitiesRepository.save(capabilities);
            });
    }
}
