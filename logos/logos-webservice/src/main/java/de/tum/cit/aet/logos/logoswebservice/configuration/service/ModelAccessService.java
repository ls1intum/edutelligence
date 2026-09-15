package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.common.NotFoundException;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ModelAccessResponseDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ModelAccessResponseDTO.HostingProviderDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ModelAccessResponseDTO.KeyAccessDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ModelAccessResponseDTO.ModelDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ModelAccessResponseDTO.ProviderGrantDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.dto.ModelAccessResponseDTO.TeamAccessDTO;
import de.tum.cit.aet.logos.logoswebservice.configuration.entity.ModelCapabilities;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelAccessMatrixProjection;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelCapabilitiesRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelProviderRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelWithPriceProjection;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TeamModelPermissionRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.CustomPermissionKeyProjection;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.KeyProviderGrantProjection;

/**
 * Builds the read-only access matrix for a single model: its hosting
 * providers, the team-level model/provider grants, and the custom-permission
 * API keys with grants touching the model. Effective access is the model
 * grant AND at least one grant on a hosting provider — the cross-check that
 * the per-team permission endpoints cannot express.
 */
@Service
public class ModelAccessService {

    private final ModelRepository modelRepository;
    private final ModelProviderRepository modelProviderRepository;
    private final TeamModelPermissionRepository teamModelPermissionRepository;
    private final ModelCapabilitiesRepository modelCapabilitiesRepository;
    private final ApiKeyRepository apiKeyRepository;

    public ModelAccessService(ModelRepository modelRepository,
                              ModelProviderRepository modelProviderRepository,
                              TeamModelPermissionRepository teamModelPermissionRepository,
                              ModelCapabilitiesRepository modelCapabilitiesRepository,
                              ApiKeyRepository apiKeyRepository) {
        this.modelRepository = modelRepository;
        this.modelProviderRepository = modelProviderRepository;
        this.teamModelPermissionRepository = teamModelPermissionRepository;
        this.modelCapabilitiesRepository = modelCapabilitiesRepository;
        this.apiKeyRepository = apiKeyRepository;
    }

    public ModelAccessResponseDTO getModelAccess(int modelId) {
        ModelWithPriceProjection model = modelRepository.findWithPricingById(modelId)
            .orElseThrow(() -> new NotFoundException("Model not found: " + modelId));

        List<HostingProviderDTO> providers = modelProviderRepository
            .findHostingProvidersWithUsage(modelId).stream()
            .map(p -> new HostingProviderDTO(
                p.getProviderId(), p.getName(), p.getProviderType(), p.getPrivacyLevel(),
                p.getRequestCount(), p.getLastRequestAt()))
            .toList();

        ModelDTO modelDTO = new ModelDTO(
            model.getId(),
            model.getName() != null ? model.getName() : "Model " + modelId,
            model.getDescription(),
            model.getTags(),
            splitAliases(model.getAliases()),
            model.getInputUsdPerMillion(),
            model.getOutputUsdPerMillion(),
            modelCapabilitiesRepository.findByModelId(modelId)
                .map(ModelCapabilities::getMaxInputTokens)
                .orElse(null),
            model.getLastUsedAt());

        return new ModelAccessResponseDTO(
            modelDTO,
            providers,
            buildTeamAccess(modelId, providers),
            buildKeyAccess(modelId, providers));
    }

    /**
     * Folds the (team × host provider) matrix rows into one row per team, in
     * team-id order. The provider grant list follows the provider list order
     * so every row carries the same columns.
     */
    private List<TeamAccessDTO> buildTeamAccess(int modelId, List<HostingProviderDTO> providers) {
        Map<Integer, ModelAccessMatrixProjection> teamRows = new LinkedHashMap<>();
        Map<Integer, Map<Integer, Boolean>> providerGrants = new HashMap<>();
        for (ModelAccessMatrixProjection row : teamModelPermissionRepository.findModelAccessMatrix(modelId)) {
            teamRows.putIfAbsent(row.getTeamId(), row);
            if (row.getProviderId() != null) {
                providerGrants.computeIfAbsent(row.getTeamId(), k -> new HashMap<>())
                    .put(row.getProviderId(), Boolean.TRUE.equals(row.getProviderGrant()));
            }
        }

        List<TeamAccessDTO> teams = new ArrayList<>(teamRows.size());
        for (Map.Entry<Integer, ModelAccessMatrixProjection> entry : teamRows.entrySet()) {
            int teamId = entry.getKey();
            boolean modelGrant = Boolean.TRUE.equals(entry.getValue().getModelGrant());
            Map<Integer, Boolean> grants = providerGrants.getOrDefault(teamId, Map.of());
            List<ProviderGrantDTO> grantsDTO = providerGrantsFor(providers, pid -> grants.getOrDefault(pid, false));
            teams.add(new TeamAccessDTO(
                teamId,
                entry.getValue().getTeamName(),
                modelGrant,
                grantsDTO,
                effective(modelGrant, grantsDTO)));
        }
        return teams;
    }

    private List<KeyAccessDTO> buildKeyAccess(int modelId, List<HostingProviderDTO> providers) {
        List<CustomPermissionKeyProjection> keys = apiKeyRepository.findCustomPermissionKeysForModel(modelId);
        if (keys.isEmpty()) {
            return List.of();
        }

        List<Integer> keyIds = keys.stream().map(CustomPermissionKeyProjection::getKeyId).toList();
        // Grouped by key; the query already restricts to hosting providers.
        Map<Integer, Set<Integer>> grantedProviderIds = apiKeyRepository.findProviderGrantsForKeys(keyIds, modelId)
            .stream()
            .collect(Collectors.groupingBy(
                KeyProviderGrantProjection::getApiKeyId,
                Collectors.mapping(KeyProviderGrantProjection::getProviderId, Collectors.toSet())));

        return keys.stream().map(key -> {
            Set<Integer> granted = grantedProviderIds.getOrDefault(key.getKeyId(), Set.of());
            List<ProviderGrantDTO> grantsDTO = providerGrantsFor(providers, granted::contains);
            boolean modelGrant = Boolean.TRUE.equals(key.getModelGrant());
            return new KeyAccessDTO(
                key.getKeyId(),
                key.getKeyName(),
                key.getIsActive(),
                key.getTeamId(),
                key.getTeamName(),
                modelGrant,
                grantsDTO,
                effective(modelGrant, grantsDTO));
        }).toList();
    }

    /** One entry per hosting provider, in provider list order. */
    private List<ProviderGrantDTO> providerGrantsFor(
            List<HostingProviderDTO> providers, Function<Integer, Boolean> grantLookup) {
        return providers.stream()
            .map(p -> new ProviderGrantDTO(p.providerId(), grantLookup.apply(p.providerId())))
            .toList();
    }

    private static boolean effective(boolean modelGrant, List<ProviderGrantDTO> providerGrants) {
        return modelGrant && providerGrants.stream().anyMatch(ProviderGrantDTO::granted);
    }

    /** get_models joins aliases with ", "; aliases may not contain commas. */
    private static List<String> splitAliases(String joined) {
        if (joined == null || joined.isBlank()) {
            return List.of();
        }
        return Arrays.stream(joined.split(", ")).toList();
    }
}
