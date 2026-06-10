package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.util.Map;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;

@Service
public class StatsService {

    private final ModelRepository modelRepository;
    private final ApiKeyRepository apiKeyRepository;
    private final ProviderRepository providerRepository;
    private final LogEntryRepository logEntryRepository;

    public StatsService(ModelRepository modelRepository,
                        ApiKeyRepository apiKeyRepository,
                        ProviderRepository providerRepository,
                        LogEntryRepository logEntryRepository) {
        this.modelRepository = modelRepository;
        this.apiKeyRepository = apiKeyRepository;
        this.providerRepository = providerRepository;
        this.logEntryRepository = logEntryRepository;
    }

    public Map<String, Object> generalStats() {
        long models = modelRepository.count();
        long apiKeys = apiKeyRepository.countByIsActive(true);
        long requests = logEntryRepository.count();
        return Map.of("models", models, "api_keys", apiKeys, "requests", requests);
    }

    public Map<String, Object> generalModelStats() {
        return Map.of("totalModels", modelRepository.count());
    }

    public Map<String, Object> generalProviderStats() {
        return Map.of("totalProviders", providerRepository.count());
    }
}
