package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.Objects;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelCapabilities;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelCapabilitiesRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;

@Service
public class ModelCapabilitiesPersistenceService {

    private static final Logger log = LoggerFactory.getLogger(ModelCapabilitiesPersistenceService.class);

    private final ModelCapabilitiesRepository modelCapabilitiesRepository;
    private final ModelRepository modelRepository;

    public ModelCapabilitiesPersistenceService(
            ModelCapabilitiesRepository modelCapabilitiesRepository,
            ModelRepository modelRepository) {
        this.modelCapabilitiesRepository = modelCapabilitiesRepository;
        this.modelRepository = modelRepository;
    }

    /**
     * Writes what the catalog says about a model, in one transaction under the
     * model row lock. Both guards that decide whether the write may happen are
     * re-evaluated inside that transaction:
     * <ul>
     *   <li>the model must still carry the name the caller resolved against the
     *       catalog — a rename that landed in the meantime owns the row, and its
     *       own (newer) sync must not be undone by this one;</li>
     *   <li>{@code manual_override} must still be clear — an admin who set the
     *       flags by hand while this sync was running keeps them.</li>
     * </ul>
     *
     * @param found whether the catalog knows the model; when false the stored
     *              row is deleted so the UI shows "capabilities unknown"
     *              instead of the flags of the previous name
     * @return true when the row was written from the catalog
     */
    @Transactional
    public boolean applyCatalogCapabilities(
            int modelId,
            String expectedModelName,
            boolean found,
            boolean supportsFunctionCalling,
            boolean supportsVision,
            boolean supportsReasoning) {

        Model model = modelRepository.findByIdForUpdate(modelId).orElse(null);
        if (model == null || !Objects.equals(model.getName(), expectedModelName)) {
            log.debug(
                "capabilities_updater: dropping superseded sync for model id={} (name '{}' is no longer current)",
                modelId,
                expectedModelName
            );
            return false;
        }

        ModelCapabilities capabilities = modelCapabilitiesRepository.findByModelId(modelId).orElse(null);
        if (capabilities != null && capabilities.getManualOverride()) {
            log.debug("capabilities_updater: skipping model '{}' (id={}): manual override is active",
                expectedModelName, modelId);
            return false;
        }

        if (!found) {
            if (capabilities != null) {
                modelCapabilitiesRepository.delete(capabilities);
            }
            return false;
        }

        if (capabilities == null) {
            capabilities = new ModelCapabilities();
            capabilities.setModelId(modelId);
        }
        capabilities.setSupportsFunctionCalling(supportsFunctionCalling);
        capabilities.setSupportsVision(supportsVision);
        capabilities.setSupportsReasoning(supportsReasoning);
        modelCapabilitiesRepository.save(capabilities);
        return true;
    }

    @Transactional
    public boolean isManualOverride(int modelId) {

        return modelCapabilitiesRepository.findByModelId(modelId)
            .map(ModelCapabilities::getManualOverride)
            .orElse(false);
    }

    /**
     * Pins the capability flags to what an admin typed. Takes the same model row
     * lock as {@link #applyCatalogCapabilities} so a catalog sync that is already
     * running cannot slip its write in between this override and the flag that
     * protects it.
     */
    @Transactional
    public void setManualCapabilities(
            int modelId,
            boolean supportsFunctionCalling,
            boolean supportsVision,
            boolean supportsReasoning) {

        modelRepository.findByIdForUpdate(modelId);

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

    /** Hands the row back to the catalog sync, under the model row lock. */
    @Transactional
    public void clearManualOverride(int modelId) {

        modelRepository.findByIdForUpdate(modelId);

        modelCapabilitiesRepository.findByModelId(modelId)
            .ifPresent(capabilities -> {
                capabilities.setManualOverride(false);
                modelCapabilitiesRepository.save(capabilities);
            });
    }
}
