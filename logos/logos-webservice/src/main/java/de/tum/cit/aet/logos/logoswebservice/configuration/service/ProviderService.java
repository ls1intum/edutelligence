package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.AddProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ConnectModelProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.DisconnectModelProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.UpdateProviderRequestDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.CloudProviderType;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelProvider;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Provider;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ProviderType;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ThresholdLevel;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderModelProjection;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderProjection;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Role;
import de.tum.cit.aet.logos.logoswebservice.orchestrator.OrchestratorNotificationService;

@Service
public class ProviderService {

    private static final Set<String> VALID_PRIVACY_LEVELS = Set.of(
        "LOCAL", "CLOUD_IN_EU_BY_EU_PROVIDER",
        "CLOUD_IN_EU_BY_US_PROVIDER", "CLOUD_NOT_IN_EU_BY_US_PROVIDER"
    );

    private final ProviderRepository providerRepository;
    private final ModelProviderRepository modelProviderRepository;
    private final OrchestratorNotificationService orchestratorNotificationService;

    public ProviderService(ProviderRepository providerRepository,
                           ModelProviderRepository modelProviderRepository,
                           OrchestratorNotificationService orchestratorNotificationService) {
        this.providerRepository = providerRepository;
        this.modelProviderRepository = modelProviderRepository;
        this.orchestratorNotificationService = orchestratorNotificationService;
    }

    public List<Map<String, Object>> getProviders(AuthContext auth) {
        boolean admin = Role.LOGOS_ADMIN.matches(auth.role());
        List<ProviderProjection> projections = admin
            ? providerRepository.findAllForAdmin()
            : providerRepository.findAllForUser(auth.userId());
        return projections.stream().map(ProviderService::toProviderMap).toList();
    }

    @Transactional
    public Map<String, Object> addProvider(AddProviderRequestDTO req) {
        if (req.privacyLevel() == null || !VALID_PRIVACY_LEVELS.contains(req.privacyLevel())) {
            throw new IllegalArgumentException("privacy_level is required and must be one of " + VALID_PRIVACY_LEVELS);
        }
        Provider p = new Provider();
        p.setName(req.providerName());
        p.setBaseUrl(req.baseUrl());
        p.setApiKey(req.apiKey());
        p.setAuthName(req.authName() != null ? req.authName() : "");
        p.setAuthFormat(req.authFormat() != null ? req.authFormat() : "");
        p.setProviderType(parseProviderType(req.providerType()));
        p.setCloudProviderType(parseCloudProviderType(req.cloudProviderType()));
        p.setPrivacyLevel(ThresholdLevel.valueOf(req.privacyLevel()));
        p = providerRepository.save(p);
        orchestratorNotificationService.notifyRefresh(false);
        return Map.of("result", "Created Provider.", "provider-id", p.getId());
    }

    @Transactional
    public Map<String, Object> updateProvider(UpdateProviderRequestDTO req) {
        Provider p = providerRepository.findById(req.providerId())
            .orElseThrow(() -> new IllegalArgumentException("Provider not found: " + req.providerId()));
        if (req.providerName() != null) p.setName(req.providerName());
        if (req.baseUrl() != null) p.setBaseUrl(req.baseUrl());
        if (req.apiKey() != null) p.setApiKey(req.apiKey());
        if (req.authName() != null) p.setAuthName(req.authName());
        if (req.authFormat() != null) p.setAuthFormat(req.authFormat());
        if (req.providerType() != null) p.setProviderType(parseProviderType(req.providerType()));
        if (req.cloudProviderType() != null) p.setCloudProviderType(parseCloudProviderType(req.cloudProviderType()));
        if (req.privacyLevel() != null) {
            if (!VALID_PRIVACY_LEVELS.contains(req.privacyLevel())) {
                throw new IllegalArgumentException("Invalid privacy_level");
            }
            p.setPrivacyLevel(ThresholdLevel.valueOf(req.privacyLevel()));
        }
        providerRepository.save(p);
        orchestratorNotificationService.notifyRefresh(false);
        return Map.of("result", "Updated Provider.");
    }

    @Transactional
    public Map<String, Object> deleteProvider(Integer providerId) {
        if (!providerRepository.existsById(providerId)) {
            throw new IllegalArgumentException("Provider not found: " + providerId);
        }
        providerRepository.deleteById(providerId);
        orchestratorNotificationService.notifyRefresh(false);
        return Map.of("result", "Deleted Provider.");
    }

    @Transactional
    public Map<String, Object> connectModelProvider(ConnectModelProviderRequestDTO req) {
        ModelProvider mp = modelProviderRepository
            .findByModelIdAndProviderId(req.modelId(), req.providerId())
            .orElseGet(() -> {
                ModelProvider n = new ModelProvider();
                n.setModelId(req.modelId());
                n.setProviderId(req.providerId());
                return n;
            });
        mp.setApiKey(req.apiKey());
        mp.setEndpoint(req.endpoint());
        mp = modelProviderRepository.save(mp);
        orchestratorNotificationService.notifyRefresh(false);
        return Map.of("result", "Connected Model to Provider. ID: " + mp.getId() + ".");
    }

    @Transactional
    public Map<String, Object> disconnectModelProvider(DisconnectModelProviderRequestDTO req) {
        if (modelProviderRepository.findByModelIdAndProviderId(req.modelId(), req.providerId()).isEmpty()) {
            throw new IllegalArgumentException("Connection not found.");
        }
        modelProviderRepository.deleteByModelIdAndProviderId(req.modelId(), req.providerId());
        orchestratorNotificationService.notifyRefresh(false);
        return Map.of("result", "Disconnected model from provider.");
    }

    public List<Map<String, Object>> getProviderModels(Integer providerId) {
        return modelProviderRepository.findModelsForProvider(providerId).stream()
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("model_id", p.getModelId());
                m.put("model_name", p.getModelName());
                m.put("endpoint", p.getEndpoint() != null ? p.getEndpoint() : "");
                m.put("api_key", p.getApiKey() != null ? p.getApiKey() : "");
                return m;
            })
            .toList();
    }

    public Map<String, Object> getGeneralProviderStats() {
        return Map.of("totalProviders", providerRepository.count());
    }

    private static ProviderType parseProviderType(String raw) {
        if (raw == null) return ProviderType.logosnode;
        String normalized = raw.toLowerCase();
        if (List.of("node", "node_controller", "ollama", "logos_worker_node").contains(normalized)) {
            return ProviderType.logosnode;
        }
        try { return ProviderType.valueOf(normalized); }
        catch (IllegalArgumentException e) { return ProviderType.logosnode; }
    }

    private static CloudProviderType parseCloudProviderType(String raw) {
        if (raw == null || raw.equalsIgnoreCase("none")) return null;
        try { return CloudProviderType.valueOf(raw.toLowerCase()); }
        catch (IllegalArgumentException e) { return null; }
    }

    private static Map<String, Object> toProviderMap(ProviderProjection p) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", p.getId());
        m.put("name", p.getName());
        m.put("base_url", p.getBaseUrl());
        m.put("api_key", p.getApiKey());
        m.put("provider_type", p.getProviderType());
        m.put("cloud_provider_type", p.getCloudProviderType());
        m.put("privacy_level", p.getPrivacyLevel());
        m.put("auth_name", p.getAuthName());
        m.put("auth_format", p.getAuthFormat());
        return m;
    }
}
