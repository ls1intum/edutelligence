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
     *   <li>when {@code manual_override} is set, the three boolean flags stay as
     *       the admin left them and the row is never deleted — only
     *       {@code max_input_tokens} follows the catalog (or is cleared on
     *       no-match).</li>
     * </ul>
     *
     * @param found whether the catalog knows the model; when false and the row
     *              is not manually overridden, the stored row is deleted so the
     *              UI shows "capabilities unknown" instead of the flags of the
     *              previous name
     * @return true when the row was written from the catalog (including a
     *         window-only update under a manual override)
     */
    @Transactional
    public boolean applyCatalogCapabilities(
            int modelId,
            String expectedModelName,
            boolean found,
            boolean supportsFunctionCalling,
            boolean supportsVision,
            boolean supportsReasoning,
            Integer maxInputTokens) {

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
        boolean manualOverride = capabilities != null && capabilities.getManualOverride();

        if (!found) {
            if (capabilities == null) {
                return false;
            }
            if (manualOverride) {
                // Keep the admin's flags; drop only the catalog window so
                // /v1/models does not advertise the previous name's limit.
                capabilities.setMaxInputTokens(null);
                modelCapabilitiesRepository.save(capabilities);
                return false;
            }
            modelCapabilitiesRepository.delete(capabilities);
            return false;
        }

        if (capabilities == null) {
            capabilities = new ModelCapabilities();
            capabilities.setModelId(modelId);
        }
        if (!manualOverride) {
            capabilities.setSupportsFunctionCalling(supportsFunctionCalling);
            capabilities.setSupportsVision(supportsVision);
            capabilities.setSupportsReasoning(supportsReasoning);
        }
        // Set unconditionally, including null: a registry refresh that drops
        // the model's window must clear a value an older refresh recorded.
        // Under a manual override the flags stay pinned, but the window still
        // tracks the catalog so a rename cannot leave a stale limit advertised.
        capabilities.setMaxInputTokens(maxInputTokens);

        modelCapabilitiesRepository.save(capabilities);
        return true;
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
